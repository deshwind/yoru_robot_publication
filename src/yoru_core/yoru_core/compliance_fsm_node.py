"""Compliance FSM node (dissertation Sections 3.9 and 4.7).

Five-stage graduated escalation:

  S0 MONITORING      confirmed event must persist before escalation
  S1 PA_WARNING      public-address audio warning
  S2 APPROACH        Nav2 navigates to a social standoff distance
  S3 DIRECT_WARNING  close-range verbal warning
  S4 LOGGING         privacy-preserving incident logging, then back to S0
     SAFE_STOP       emergency stop (obstacle), cooldown, back to S0

Safety overrides: obstacle stop (< obstacle_stop_distance during APPROACH),
target loss (track gone > target_lost_timeout), per-person cooldown,
compliance reset at any stage after compliance_clear_duration.

Instrumentation (evaluation): /compliance/fsm_state (std_msgs/String JSON)
carries every transition with stamp, previous/new state, reason, track and
room, plus a 'cooldown_end' event when a track's cooldown expires.
"""

import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
from vision_msgs.msg import Detection2DArray

PA_MESSAGE = 'Smoking is not allowed here. Please stop immediately.'
DIRECT_MESSAGE = ('This is a final warning. Smoking is not allowed here. '
                  'This incident has been recorded and will be reported.')


class ComplianceFsmNode(Node):

    def __init__(self):
        super().__init__('compliance_fsm_node')

        # false: every duration uses the wall clock (time.monotonic), as
        # deployed. true: use the node clock, i.e. sim time when
        # use_sim_time is set - evaluation runs, so windows match bag stamps.
        self.declare_parameter('use_ros_clock', False)
        self.use_ros_clock = bool(self.get_parameter('use_ros_clock').value)

        self.declare_parameter('monitor_confirm_duration', 3.0)
        self.declare_parameter('pa_warning_duration', 15.0)
        self.declare_parameter('approach_timeout', 60.0)
        self.declare_parameter('direct_warning_duration', 15.0)
        # The robot repeats the direct warning this many times on arrival,
        # spaced by the interval; the incident email goes out afterwards
        self.declare_parameter('direct_warning_repeats', 3)
        self.declare_parameter('direct_warning_interval', 8.0)
        self.declare_parameter('logging_duration', 2.0)
        self.declare_parameter('safe_stop_duration', 3.0)
        self.declare_parameter('compliance_clear_duration', 10.0)
        self.declare_parameter('cooldown_duration', 60.0)
        self.declare_parameter('obstacle_stop_distance', 0.35)
        self.declare_parameter('scan_ignore_radius', 0.2)
        # A single close reading (rotation grazing the robot's own mast/
        # camera mount for one frame) must not kill the whole approach;
        # require the obstacle to persist this long before stopping.
        self.declare_parameter('obstacle_debounce_duration', 0.4)
        # A real obstacle reflects several adjacent lidar beams; a lidar that
        # is browning out (USB undervoltage) emits isolated noise spikes.
        # Require at least this many beams inside the stop distance before
        # treating it as a real obstacle, so noise can't abort the approach.
        self.declare_parameter('min_obstacle_beams', 4)
        # The e-stop only watches a forward-facing arc: the robot drives
        # forward, so a wall behind or beside it must not stop it - only
        # things in its path. center 0 = lidar forward (mount is unrotated);
        # halfwidth 1.047 rad = a 120-degree front cone. If the sensor's 0
        # mark is not physically forward, set obstacle_fov_center (pi = rear).
        self.declare_parameter('obstacle_fov_center', 0.0)
        self.declare_parameter('obstacle_fov_halfwidth', 1.047)
        self.declare_parameter('target_lost_timeout', 5.0)
        # One confirmed-events topic per CCTV pipeline
        self.declare_parameter('events_topics', ['/compliance/confirmed_events'])
        self.declare_parameter('pa_message', PA_MESSAGE)
        self.declare_parameter('direct_message', DIRECT_MESSAGE)

        self.state = 'MONITORING'
        self.state_since = self.now_s()
        self.target_track = None
        self.target_class = None
        self.track_first_seen = {}
        self.track_last_seen = {}
        self.track_metadata = {}
        # Camera-level continuity: the tracker reassigns IDs when a person
        # or device moves, but a confirmed violation from the same camera
        # is treated as the same ongoing event (one room, one violator).
        self.room_first_seen = {}
        self.room_last_seen = {}
        self.cooldowns = {}
        self.obstacle_since = None
        self.close_beam_count = 0
        self.min_scan_range = float('inf')
        self.nav_result = None
        self.stage_reached = 'S0'
        self.autonomy_paused = False
        self.direct_count = 0
        self.last_direct_time = 0.0

        self.status_pub = self.create_publisher(String, '/compliance/fsm_status', 10)
        self.pa_pub = self.create_publisher(String, '/compliance/pa_warning', 10)
        self.direct_pub = self.create_publisher(String, '/compliance/direct_warning', 10)
        self.incident_pub = self.create_publisher(String, '/compliance/incident_log', 10)
        # cmd_vel_tracker has higher twist_mux priority than Nav2's cmd_vel,
        # so publishing zeros here overrides navigation for an emergency stop.
        self.estop_pub = self.create_publisher(Twist, 'cmd_vel_tracker', 10)
        # Evaluation instrumentation: one message per transition (plus
        # cooldown expiries), stamped with the node clock (sim time in Gazebo)
        self.fsm_state_pub = self.create_publisher(
            String, '/compliance/fsm_state', 50)
        self.cooldown_reported = {}  # track -> cooldown start already reported

        for topic in self.get_parameter('events_topics').value:
            self.create_subscription(Detection2DArray, topic,
                                     self.events_callback, 10)
        self.create_subscription(String, '/compliance/event_metadata',
                                 self.metadata_callback, 10)
        self.create_subscription(String, '/compliance/nav_status',
                                 self.nav_status_callback, 10)
        self.create_subscription(LaserScan, '/scan', self.scan_callback,
                                 rclpy.qos.qos_profile_sensor_data)
        self.create_subscription(Bool, '/compliance/autonomy_paused',
                                 self.paused_callback, 10)
        self.create_timer(0.1, self.tick)

        self.get_logger().info('Compliance FSM ready (state: MONITORING)')

    # ------------------------------------------------------------------ inputs

    def events_callback(self, msg):
        now = self.now_s()
        for det in msg.detections:
            track = det.id or 'untracked'
            if track not in self.track_first_seen:
                self.track_first_seen[track] = now
            self.track_last_seen[track] = now

    def metadata_callback(self, msg):
        try:
            meta = json.loads(msg.data)
        except ValueError:
            return
        if meta.get('status') == 'confirmed':
            self.track_metadata[meta.get('track_id')] = meta
            room = meta.get('room')
            if room:
                now = self.now_s()
                quiet = self.param('compliance_clear_duration')
                if room not in self.room_last_seen or \
                        now - self.room_last_seen[room] > quiet:
                    self.room_first_seen[room] = now  # fresh violation
                self.room_last_seen[room] = now

    def nav_status_callback(self, msg):
        try:
            self.nav_result = json.loads(msg.data).get('state')
        except ValueError:
            return

    def scan_callback(self, msg):
        # Returns inside scan_ignore_radius are the robot seeing its own
        # frame/mast (measured ~0.18 m on Yoru) - without this filter the
        # obstacle e-stop trips the moment APPROACH starts. Real obstacle
        # avoidance is Nav2's costmaps; this check is only the e-stop.
        ignore = self.param('scan_ignore_radius')
        stop = self.param('obstacle_stop_distance')
        center = self.param('obstacle_fov_center')
        half = self.param('obstacle_fov_halfwidth')
        # Only beams in the forward cone count: a wall behind/beside the
        # robot is not in its path and must not trip the approach e-stop.
        valid = []
        for i, r in enumerate(msg.ranges):
            if not (msg.range_min < r < msg.range_max and r > ignore):
                continue
            angle = msg.angle_min + i * msg.angle_increment
            delta = math.atan2(math.sin(angle - center), math.cos(angle - center))
            if abs(delta) <= half:
                valid.append(r)
        self.min_scan_range = min(valid) if valid else float('inf')
        # How many forward beams fall inside the stop distance - a real
        # obstacle lights up many; a noisy/browning-out lidar only a stray few.
        self.close_beam_count = sum(1 for r in valid if r < stop)

    def paused_callback(self, msg):
        if msg.data != self.autonomy_paused:
            self.autonomy_paused = msg.data
            self.get_logger().warn(
                'Autonomy paused by admin' if msg.data else 'Autonomy resumed')

    # ----------------------------------------------------------------- helpers

    def param(self, name):
        return self.get_parameter(name).value

    def now_s(self):
        if self.use_ros_clock:
            return self.get_clock().now().nanoseconds * 1e-9
        return time.monotonic()

    def elapsed(self):
        return self.now_s() - self.state_since

    def transition(self, new_state, reason, track=None, room=None, **extra):
        self.get_logger().info(
            f'FSM: {self.state} -> {new_state} '
            f'(track={self.target_track}, after {self.elapsed():.1f}s)')
        if track is None:
            track = self.target_track
            room = self.track_metadata.get(track, {}).get('room', '')
        self.publish_fsm_state(self.state, new_state, reason, track, room,
                               time_in_state=round(self.elapsed(), 3), **extra)
        self.state = new_state
        self.state_since = self.now_s()
        self.publish_status()

    def publish_fsm_state(self, previous, new, reason, track, room, **extra):
        stamp = self.get_clock().now()
        event = {
            'stamp': stamp.nanoseconds * 1e-9,
            'previous_state': previous,
            'new_state': new,
            'reason': reason,
            'track_id': track,
            'room': room or '',
            'stage_reached': self.stage_reached,
            'direct_count': self.direct_count,
            'clock': 'ros' if self.use_ros_clock else 'wall',
        }
        event.update(extra)
        msg = String()
        msg.data = json.dumps(event)
        self.fsm_state_pub.publish(msg)

    def report_cooldown_ends(self):
        """Instrumentation only: announce each per-track cooldown expiry
        once. Reads self.cooldowns, never changes it."""
        cooldown = self.param('cooldown_duration')
        now = self.now_s()
        for track, started in self.cooldowns.items():
            if now - started >= cooldown and \
                    self.cooldown_reported.get(track) != started:
                self.cooldown_reported[track] = started
                self.publish_fsm_state(self.state, self.state, 'cooldown_end',
                                       track, '', cooldown_started=started)

    def publish_status(self):
        meta = self.track_metadata.get(self.target_track, {})
        msg = String()
        msg.data = json.dumps({
            'state': self.state,
            'track_id': self.target_track,
            'room': meta.get('room', ''),
            'elapsed': round(self.elapsed(), 1),
            'stage_reached': self.stage_reached,
        })
        self.status_pub.publish(msg)

    def _target_last_seen(self):
        """Freshest evidence for the target: its own track, or any confirmed
        event from the same camera (ID churn = same ongoing violation)."""
        candidates = [self.track_last_seen.get(self.target_track)]
        room = self.track_metadata.get(self.target_track, {}).get('room')
        if room:
            candidates.append(self.room_last_seen.get(room))
        candidates = [c for c in candidates if c is not None]
        return max(candidates) if candidates else None

    def target_active(self):
        """Violation still ongoing for the current target (or its camera)."""
        if self.target_track is None:
            return False
        last = self._target_last_seen()
        return last is not None and \
            self.now_s() - last < self.param('compliance_clear_duration')

    def target_lost(self):
        if self.target_track is None:
            return True
        last = self._target_last_seen()
        return last is None or \
            self.now_s() - last > self.param('target_lost_timeout')

    def log_incident(self, outcome):
        meta = self.track_metadata.get(self.target_track, {})
        incident = {
            'track_id': self.target_track,
            'room': meta.get('room', ''),
            'event_class': self.target_class,
            'stage_reached': self.stage_reached,
            'outcome': outcome,
            'confidence': meta.get('confidence'),
            'criteria': meta.get('criteria'),
        }
        msg = String()
        msg.data = json.dumps(incident)
        self.incident_pub.publish(msg)

    def finish_escalation(self, outcome):
        track = self.target_track
        room = self.track_metadata.get(track, {}).get('room', '')
        stage = self.stage_reached  # reset to S0 below; the event reports it
        self.log_incident(outcome)
        if self.target_track is not None:
            self.cooldowns[self.target_track] = self.now_s()
        self.target_track = None
        self.target_class = None
        self.nav_result = None
        self.stage_reached = 'S0'
        self.direct_count = 0
        self.transition('MONITORING', outcome, track=track, room=room,
                        outcome=outcome, stage_reached=stage)

    def send_direct_warning(self):
        meta = self.track_metadata.get(self.target_track, {})
        direct = String()
        direct.data = json.dumps({'message': self.param('direct_message'),
                                  'track_id': self.target_track,
                                  'room': meta.get('room', ''),
                                  'event_class': self.target_class})
        self.direct_pub.publish(direct)
        self.direct_count += 1
        self.last_direct_time = self.now_s()
        self.get_logger().info(
            f'Direct warning {self.direct_count}/'
            f'{int(self.param("direct_warning_repeats"))}')

    # -------------------------------------------------------------------- tick

    def tick(self):
        now = self.now_s()
        self.report_cooldown_ends()

        # Admin override: abort any active escalation and stay in MONITORING
        if self.autonomy_paused:
            if self.state != 'MONITORING':
                self.get_logger().warn('Escalation aborted: admin paused autonomy')
                self.finish_escalation('admin_override')
            return

        # Compliance reset is checked in every escalation stage
        in_escalation = self.state in ('PA_WARNING', 'APPROACH', 'DIRECT_WARNING')
        if in_escalation and not self.target_active():
            self.get_logger().info(
                f'Compliance detected at {self.state}; resetting to MONITORING')
            self.finish_escalation('complied')
            return

        if self.state == 'MONITORING':
            self.monitoring_tick(now)
        elif self.state == 'PA_WARNING':
            if self.elapsed() >= self.param('pa_warning_duration'):
                self.stage_reached = 'S2'
                self.obstacle_since = None
                self.transition('APPROACH', 'pa_expired')
        elif self.state == 'APPROACH':
            self.approach_tick()
        elif self.state == 'DIRECT_WARNING':
            # Repeat the warning N times, then log + email the evidence.
            # direct_warning_duration remains as an overall safety cap.
            interval_over = (self.now_s() - self.last_direct_time
                             >= self.param('direct_warning_interval'))
            if interval_over:
                if self.direct_count < int(self.param('direct_warning_repeats')):
                    self.send_direct_warning()
                else:
                    self.stage_reached = 'S4'
                    self.transition('LOGGING', 'warnings_complete')
            if self.state == 'DIRECT_WARNING' and \
                    self.elapsed() >= self.param('direct_warning_duration'):
                self.stage_reached = 'S4'
                self.transition('LOGGING', 'direct_warning_cap')
        elif self.state == 'LOGGING':
            if self.elapsed() >= self.param('logging_duration'):
                self.finish_escalation('logged_no_compliance')
        elif self.state == 'SAFE_STOP':
            self.estop_pub.publish(Twist())  # zero velocity overrides Nav2
            if self.elapsed() >= self.param('safe_stop_duration'):
                self.finish_escalation('safety_stop')

        if int(self.elapsed() * 10) % 10 == 0:  # ~1 Hz heartbeat
            self.publish_status()

    def monitoring_tick(self, now):
        cooldown = self.param('cooldown_duration')
        confirm = self.param('monitor_confirm_duration')
        for track, first in list(self.track_first_seen.items()):
            last = self.track_last_seen.get(track, 0.0)
            if now - last > self.param('compliance_clear_duration'):
                # Stale track: forget it (volatile state, privacy design)
                self.track_first_seen.pop(track, None)
                self.track_last_seen.pop(track, None)
                self.track_metadata.pop(track, None)
                continue
            if track in self.cooldowns and now - self.cooldowns[track] < cooldown:
                continue
            # Same-camera continuity: a reassigned track ID (person or vape
            # moved) inherits the room's ongoing violation start time, so
            # the confirm window doesn't restart on every ID churn.
            room = self.track_metadata.get(track, {}).get('room')
            if room and room in self.room_first_seen and \
                    now - self.room_last_seen.get(room, 0.0) <= \
                    self.param('compliance_clear_duration'):
                first = min(first, self.room_first_seen[room])
            if now - first >= confirm:
                self.target_track = track
                meta = self.track_metadata.get(track, {})
                self.target_class = meta.get('event_class', 'cigarette')
                self.stage_reached = 'S1'
                room = meta.get('room', '')
                message = self.param('pa_message')
                if room:
                    spoken_room = room.replace('_', ' ')
                    message = (f'Attention. Smoking detected in {spoken_room}. '
                               + message)
                pa = String()
                pa.data = json.dumps({'message': message, 'track_id': track,
                                      'room': room,
                                      'event_class': self.target_class})
                self.pa_pub.publish(pa)
                self.transition('PA_WARNING', 'confirmed')
                return

    def approach_tick(self):
        if self.close_beam_count >= int(self.param('min_obstacle_beams')):
            now = self.now_s()
            if self.obstacle_since is None:
                self.obstacle_since = now
            elif now - self.obstacle_since >= \
                    self.param('obstacle_debounce_duration'):
                self.get_logger().warn(
                    f'Obstacle at {self.min_scan_range:.2f} m, '
                    f'{self.close_beam_count} beams '
                    f'(persisted {now - self.obstacle_since:.1f}s): SAFE_STOP')
                self.estop_pub.publish(Twist())
                self.transition('SAFE_STOP', 'safe_stop',
                                min_scan_range=self.min_scan_range,
                                close_beams=self.close_beam_count)
                return
        else:
            self.obstacle_since = None
        if self.target_lost():
            self.get_logger().info('Target lost during approach')
            self.finish_escalation('target_lost')
            return
        if self.nav_result == 'succeeded':
            self.nav_result = None
            self.stage_reached = 'S3'
            self.direct_count = 0
            self.send_direct_warning()   # warning 1 of N; the rest follow
            self.transition('DIRECT_WARNING', 'goal_reached')
            return
        if self.nav_result in ('aborted', 'timeout', 'rejected', 'nav2_unavailable'):
            self.get_logger().warn(f'Approach failed ({self.nav_result}); logging')
            nav_result = self.nav_result
            self.nav_result = None
            self.stage_reached = 'S4'
            self.transition('LOGGING', 'approach_failed', nav_result=nav_result)
            return
        if self.elapsed() >= self.param('approach_timeout'):
            self.stage_reached = 'S4'
            self.transition('LOGGING', 'approach_timeout')


def main(args=None):
    rclpy.init(args=args)
    node = ComplianceFsmNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
