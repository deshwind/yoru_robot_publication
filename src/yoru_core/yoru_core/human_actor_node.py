"""Human actor node: the physical half of the simulated human response model.

Drives the ROS-controlled Gazebo actors (yoru_sim_plugins/yoru_actor_plugin,
used by worlds/eval_two_room.world) so the people the CCTV sees and the
robot's lidar detects actually move:

  layout     seeded start positions; one violator + optional bystanders
  step back  after the violator stops (ground-truth 'violation_cessation'),
             it walks step_back_m directly away from the robot
  departure  on 'target_removed' it walks to exit_position (out of the
             CCTV view): the realistic form of target loss
  wander     bystanders (and the violator in a walking-only scenario)
             stroll between seeded points
  intruder   a person steps into the robot's path while the FSM is in
             intruder_trigger_state (Scenario K, SAFE_STOP)
  admin      the human operator pauses autonomy (dashboard Pause, i.e.
             /compliance/autonomy_paused = true) admin_override_delay s
             into admin_override_state (Scenario L)

Publishes /compliance/actor_events (std_msgs/String JSON, latched): the
layout and every scripted movement, stamped with the node clock (sim time).
Ground-truth positions over time come from /gazebo/model_states.
"""

import json
import math
import random

import rclpy
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String

from yoru_core.scenario_model import flat_to_triples, scenario_layout

# Start positions in room A (x, y, yaw facing CCTV 1): all fully inside the
# cctv1 image, >= 1.2 m from the cctv1 camera spot (1.8, 0), clear of the
# furniture. See evidence/README.md (Phase 3) for how they were checked.
DEFAULT_STARTS = [3.0, 0.3, -0.107, 3.4, -1.2, 0.464, 2.6, 1.4, -0.412,
                  3.9, 0.9, -0.442, 2.3, -1.5, 0.405, 3.9, -0.4, 0.207]


def yaw_quaternion(yaw):
    return math.sin(yaw / 2.0), math.cos(yaw / 2.0)


class HumanActorNode(Node):

    def __init__(self):
        super().__init__('human_actor_node')

        self.declare_parameter('seed', 0)
        self.declare_parameter('scenario_type', 'smoking')
        self.declare_parameter('actors', ['person_1', 'person_2', 'person_3'])
        self.declare_parameter('n_persons', 1)
        self.declare_parameter('start_positions', DEFAULT_STARTS)
        self.declare_parameter('robot_model', 'yoru_robot')
        self.declare_parameter('step_back_m', 0.0)
        self.declare_parameter('exit_position', [5.5, -3.6])
        self.declare_parameter('bystander_motion', 'static')  # static|wander
        self.declare_parameter('wander_area', [1.8, 4.2, -2.0, 2.0])
        self.declare_parameter('wander_pause', [2.0, 6.0])
        self.declare_parameter('intruder_enabled', False)
        self.declare_parameter('intruder_actor', 'intruder_1')
        self.declare_parameter('intruder_trigger_state', 'APPROACH')
        self.declare_parameter('intruder_trigger_delay', 2.0)
        # ... and only once the robot is past this x (e.g. through the
        # doorway into room A, so the crossing point is inside the room)
        self.declare_parameter('intruder_trigger_min_x', -100.0)
        # The intruder crosses the robot-goal line intruder_lead_m ahead of
        # the robot, coming from intruder_lateral_m to the side
        self.declare_parameter('intruder_lead_m', 1.0)
        self.declare_parameter('intruder_lateral_m', -2.0)
        self.declare_parameter('intruder_dwell', 4.0)
        self.declare_parameter('admin_override_state', '')  # '' = never
        self.declare_parameter('admin_override_delay', 3.0)
        self.declare_parameter('ground_truth_topic',
                               '/compliance/scenario_ground_truth')

        p = self.get_parameter
        self.seed = int(p('seed').value)
        self.scenario = p('scenario_type').value
        self.rng = random.Random(f'actors-{self.seed}')
        self.layout = scenario_layout(
            self.seed, int(p('n_persons').value),
            flat_to_triples(list(p('start_positions').value)),
            list(p('actors').value))
        self.roles = {a['actor']: a for a in self.layout}
        self.violator = next((a['actor'] for a in self.layout
                              if a['role'] == 'violator'), None)

        self.poses = {}          # model name -> (x, y)
        self.robot_yaw = 0.0
        self.robot_name = p('robot_model').value
        self.cmd_pubs = {}
        self.wander_next = {}    # actor -> sim time of its next stroll
        self.step_back_done = False
        self.departed = False
        self.intruder_phase = None
        self.intruder_time = None
        self.intruder_reached = None
        self.admin_done = False
        self.pause_pub = self.create_publisher(Bool, '/compliance/autonomy_paused', 10)
        self.fsm_state = 'MONITORING'
        self.state_since = None

        qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.event_pub = self.create_publisher(String, '/compliance/actor_events', qos)
        self.create_subscription(ModelStates, '/gazebo/model_states',
                                 self.model_states_callback, 10)
        self.create_subscription(String, p('ground_truth_topic').value,
                                 self.ground_truth_callback, qos)
        self.create_subscription(String, '/compliance/fsm_status',
                                 self.fsm_callback, 10)
        self.goal = None
        self.create_subscription(PoseStamped, '/compliance/navigation_targets',
                                 self.goal_callback, 10)
        self.placed = False
        self.create_timer(0.1, self.tick)
        self.get_logger().info(
            f'Human actor node: seed={self.seed}, violator={self.violator}, '
            f'layout={[(a["actor"], a["x"], a["y"], a["role"]) for a in self.layout]}')

    # ------------------------------------------------------------- helpers

    def now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def event(self, kind, **extra):
        record = {'stamp': self.now(), 'event': kind, 'seed': self.seed,
                  'scenario_type': self.scenario, 'violator': self.violator}
        record.update(extra)
        msg = String()
        msg.data = json.dumps(record)
        self.event_pub.publish(msg)

    def command(self, actor, x, y, yaw, teleport=False):
        if actor not in self.cmd_pubs:
            self.cmd_pubs[actor] = self.create_publisher(
                PoseStamped, f'/{actor}/cmd_pose', 10)
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'teleport' if teleport else 'world'
        msg.pose.position.x, msg.pose.position.y = float(x), float(y)
        msg.pose.orientation.z, msg.pose.orientation.w = yaw_quaternion(yaw)
        self.cmd_pubs[actor].publish(msg)

    # -------------------------------------------------------------- inputs

    def model_states_callback(self, msg):
        for name, pose in zip(msg.name, msg.pose):
            self.poses[name] = (pose.position.x, pose.position.y)
            if name == self.robot_name:
                q = pose.orientation
                self.robot_yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                                            1.0 - 2.0 * (q.y * q.y + q.z * q.z))

    def goal_callback(self, msg):
        self.goal = (msg.pose.position.x, msg.pose.position.y)

    def fsm_callback(self, msg):
        try:
            state = json.loads(msg.data).get('state', '')
        except ValueError:
            return
        if state != self.fsm_state:
            self.fsm_state = state
            self.state_since = self.now()

    def ground_truth_callback(self, msg):
        try:
            event = json.loads(msg.data).get('event')
        except ValueError:
            return
        if event == 'violation_cessation' and not self.step_back_done:
            self.step_back_done = True
            self.step_back()
        elif event == 'target_removed' and not self.departed:
            self.departed = True
            ex, ey = self.get_parameter('exit_position').value
            self.command(self.violator, ex, ey, 0.0)
            self.event('departure_start', actor=self.violator,
                       target={'x': ex, 'y': ey})

    # ------------------------------------------------------------- actions

    def step_back(self):
        distance = float(self.get_parameter('step_back_m').value)
        robot = self.poses.get(self.robot_name)
        person = self.poses.get(self.violator)
        if distance <= 0.0 or robot is None or person is None:
            self.event('step_back_skipped', actor=self.violator, step_back_m=distance)
            return
        dx, dy = person[0] - robot[0], person[1] - robot[1]
        norm = math.hypot(dx, dy) or 1.0
        tx, ty = person[0] + distance * dx / norm, person[1] + distance * dy / norm
        facing = math.atan2(-dy, -dx)  # keeps facing the robot
        self.command(self.violator, tx, ty, facing)
        self.event('step_back_start', actor=self.violator, step_back_m=distance,
                   person={'x': person[0], 'y': person[1]},
                   robot={'x': robot[0], 'y': robot[1]},
                   target={'x': tx, 'y': ty})

    def place_layout(self):
        for a in self.layout:
            self.command(a['actor'], a['x'], a['y'], a['yaw'], teleport=True)
        self.event('layout', persons=self.layout)
        self.placed = True

    def wander(self, now):
        xmin, xmax, ymin, ymax = self.get_parameter('wander_area').value
        pmin, pmax = self.get_parameter('wander_pause').value
        movers = [a['actor'] for a in self.layout if a['role'] == 'bystander']
        if self.scenario == 'walking' and self.violator:
            movers.append(self.violator)  # walking-only: nobody stands still
        for actor in movers:
            if actor not in self.wander_next:  # first pause before moving
                self.wander_next[actor] = now + self.rng.uniform(pmin, pmax)
            if now < self.wander_next[actor]:
                continue
            x, y = self.rng.uniform(xmin, xmax), self.rng.uniform(ymin, ymax)
            self.command(actor, x, y, self.rng.uniform(-math.pi, math.pi))
            self.wander_next[actor] = now + self.rng.uniform(pmin, pmax) + 4.0
            self.event('wander', actor=actor, target={'x': x, 'y': y})

    def intruder_tick(self, now):
        p = self.get_parameter
        actor = p('intruder_actor').value
        if self.intruder_phase is None:
            if self.fsm_state != p('intruder_trigger_state').value or \
                    self.state_since is None or \
                    now - self.state_since < p('intruder_trigger_delay').value:
                return
            robot = self.poses.get(self.robot_name)
            if robot is None or self.goal is None or \
                    robot[0] < p('intruder_trigger_min_x').value:
                return
            heading = math.atan2(self.goal[1] - robot[1], self.goal[0] - robot[0])
            lead, lateral = p('intruder_lead_m').value, p('intruder_lateral_m').value
            tx = robot[0] + lead * math.cos(heading)
            ty = robot[1] + lead * math.sin(heading)
            sx = tx - lateral * math.sin(heading)
            sy = ty + lateral * math.cos(heading)
            self.command(actor, sx, sy, 0.0, teleport=True)
            self.command(actor, tx, ty, heading + math.pi)  # ends facing the robot
            self.intruder_phase, self.intruder_time = 'crossing', now
            self.intruder_start = (sx, sy)
            self.intruder_target = (tx, ty)
            self.event('intruder_start', actor=actor, start={'x': sx, 'y': sy},
                       target={'x': tx, 'y': ty},
                       robot={'x': robot[0], 'y': robot[1], 'yaw': self.robot_yaw},
                       goal={'x': self.goal[0], 'y': self.goal[1]})
        elif self.intruder_phase == 'crossing':
            pos = self.poses.get(actor)
            target_reached = pos is not None and self.intruder_reached is None and \
                math.hypot(pos[0] - self.intruder_target[0],
                           pos[1] - self.intruder_target[1]) < 0.15
            if target_reached:
                self.intruder_reached = now
                self.event('intruder_in_path', actor=actor,
                           position={'x': pos[0], 'y': pos[1]})
            if self.intruder_reached is not None and \
                    now - self.intruder_reached >= p('intruder_dwell').value:
                self.command(actor, *self.intruder_start, 0.0)
                self.intruder_phase = 'leaving'
                self.event('intruder_leave', actor=actor)

    def tick(self):
        now = self.now()
        if now <= 0.0:
            return  # sim clock not running yet
        if not self.placed:
            if self.poses:  # Gazebo is up and the actors exist
                self.place_layout()
            return
        if self.get_parameter('bystander_motion').value == 'wander' or \
                self.scenario == 'walking':
            self.wander(now)
        if self.get_parameter('intruder_enabled').value:
            self.intruder_tick(now)
        self.admin_tick(now)

    def admin_tick(self, now):
        state = self.get_parameter('admin_override_state').value
        if not state or self.admin_done or self.fsm_state != state or \
                self.state_since is None or \
                now - self.state_since < self.get_parameter('admin_override_delay').value:
            return
        self.admin_done = True
        self.pause_pub.publish(Bool(data=True))
        self.event('admin_override', fsm_state=state)


def main(args=None):
    rclpy.init(args=args)
    node = HumanActorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
