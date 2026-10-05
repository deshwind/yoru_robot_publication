"""Scenario publisher for simulation testing (dissertation Section 5.1).

Until the custom six-class YOLO model is trained, this node makes the full
pipeline testable end-to-end in Gazebo by injecting synthetic cigarette /
vape detections:

  - 'augment'   : attach a device bbox to real YOLO person detections
  - 'synthetic' : publish a synthetic person + device at configured pixels
  - 'auto'      : augment when YOLO sees a person, otherwise synthetic

Scenario types map to the test scenarios in Section 5.1:
  smoking / vaping        -> Scenario A (full escalation)
  false_positive          -> Scenario B (phone near mouth, must be rejected)
  target_loss             -> Scenario C (detections stop mid-escalation)

The simulated person "complies" (device disappears) after the FSM reaches
'comply_after_stage', which exercises the compliance-reset path.

mode 'world' (evaluation; the modes above are unchanged) - the detection
half of the simulated human response model, used with eval_two_room.world:
  - persons come ONLY from real YOLO on the Gazebo CCTV image (no synthetic
    or coasted persons); a missed person is a missed person
  - the injected specialist-model detections are attached to the YOLO box
    of the violator, identified by projecting its Gazebo pose into the
    camera (CameraModel) and matching by IoU - so multi-person scenes work
  - one output frame per YOLO frame (persistence counts real frames)
  - compliance after a real warning: comply_stage none | S1 | S3_first |
    S3_last, comply_delay_s after it
  - seeded detection noise: confidence jitter, frame dropout, bbox jitter
  - scenario types add phone, pen, straw (confounders), brief_device
    (device at the mouth shorter than the persistence window),
    c7_conflict (cigarette below the C7 override + phone) and walking
"""

import json
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

from yoru_core.scenario_model import CameraModel, DetectionNoise


def make_detection(header, class_id, score, cx, cy, w, h):
    det = Detection2D()
    det.header = header
    det.bbox.center.position.x = float(cx)
    det.bbox.center.position.y = float(cy)
    det.bbox.size_x = float(w)
    det.bbox.size_y = float(h)
    hyp = ObjectHypothesisWithPose()
    hyp.hypothesis.class_id = class_id
    hyp.hypothesis.score = float(score)
    det.results.append(hyp)
    return det


class ScenarioPublisherNode(Node):

    def __init__(self):
        super().__init__('scenario_publisher_node')

        self.declare_parameter('mode', 'auto')  # auto|augment|synthetic|off
        self.declare_parameter('scenario_type', 'smoking')
        self.declare_parameter('start_delay', 20.0)
        self.declare_parameter('publish_hz', 10.0)
        self.declare_parameter('yolo_topic', '/compliance/detections_yolo')
        self.declare_parameter('output_topic', '/compliance/detections')
        self.declare_parameter('image_width', 640)
        self.declare_parameter('image_height', 480)
        self.declare_parameter('person_pixel_x', 320.0)
        self.declare_parameter('person_pixel_y', 300.0)
        self.declare_parameter('person_bbox_w', 80.0)
        self.declare_parameter('person_bbox_h', 200.0)
        self.declare_parameter('camera_frame', 'cctv_link_optical')
        self.declare_parameter('comply_after_stage', 'DIRECT_WARNING')
        self.declare_parameter('comply_delay', 5.0)
        self.declare_parameter('target_loss_after', 30.0)

        self.mode = self.get_parameter('mode').value
        self.scenario = self.get_parameter('scenario_type').value
        self.start_delay = self.get_parameter('start_delay').value
        self.comply_after_stage = self.get_parameter('comply_after_stage').value
        self.comply_delay = self.get_parameter('comply_delay').value

        self.declare_parameter('coast_duration', 3.0)
        # false: wall clock (as deployed); true: node clock (sim time), so
        # start_delay / comply_delay are measured in simulated seconds
        self.declare_parameter('use_ros_clock', False)
        self.use_ros_clock = bool(self.get_parameter('use_ros_clock').value)

        # Ground truth for evaluation (metadata only, never fed back into the
        # pipeline): which scenario runs, its seed, and the scripted actors
        # as flat [x0, y0, x1, y1, ...] world positions.
        self.declare_parameter('scenario_id', '')
        self.declare_parameter('seed', 0)
        self.declare_parameter('actor_ids', ['person_smoking'])
        self.declare_parameter('actor_positions', [3.0, 0.3])
        self.declare_parameter('ground_truth_topic',
                               '/compliance/scenario_ground_truth')

        # With the ROS clock, sim time may still be 0 (no /clock yet):
        # the scenario clock then starts on the first valid tick instead
        self.start_time = None if self.use_ros_clock else self.now_s()
        self.comply_stage_time = None
        self.complied = False
        self.latest_yolo = None
        self.latest_yolo_time = 0.0
        # Last real person bbox, kept through brief YOLO dropouts so the
        # published person position stays stable and SORT keeps the track.
        self.last_person_box = None
        self.last_person_time = 0.0

        out_topic = self.get_parameter('output_topic').value
        self.det_pub = self.create_publisher(Detection2DArray, out_topic, 10)
        # Latched so a bag recorder that starts late still receives events
        gt_qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.gt_pub = self.create_publisher(
            String, self.get_parameter('ground_truth_topic').value, gt_qos)
        self.gt_sent = set()  # one-shot events already published
        self.gt_last_state = 0.0
        self.create_subscription(
            Detection2DArray, self.get_parameter('yolo_topic').value,
            self.yolo_callback, 10)
        self.create_subscription(String, '/compliance/fsm_status', self.fsm_callback, 10)

        if self.mode == 'world':
            self.init_world()

        hz = self.get_parameter('publish_hz').value
        self.create_timer(1.0 / max(hz, 1.0), self.tick)
        self.get_logger().info(
            f'Scenario publisher: mode={self.mode}, scenario={self.scenario}, '
            f'device appears after {self.start_delay:.0f}s -> {out_topic}')

    def now_s(self):
        if self.use_ros_clock:
            return self.get_clock().now().nanoseconds * 1e-9
        return time.monotonic()

    def is_violation(self):
        if self.mode == 'world':
            return self.scenario in WORLD_VIOLATIONS
        return self.scenario in ('smoking', 'vaping', 'target_loss')

    def publish_ground_truth(self, event, once=True, **extra):
        """Scripted truth stamped with the node clock (sim time in Gazebo)."""
        if once and event in self.gt_sent:
            return
        self.gt_sent.add(event)
        ids = list(self.get_parameter('actor_ids').value)
        flat = list(self.get_parameter('actor_positions').value)
        record = {
            'stamp': self.get_clock().now().nanoseconds * 1e-9,
            'event': event,
            'scenario_id': self.get_parameter('scenario_id').value,
            'scenario_type': self.scenario,
            'seed': int(self.get_parameter('seed').value),
            'is_violation': self.is_violation(),
            'device_class': self.device_class(),
            'mode': self.mode,
            'start_delay': self.start_delay,
            'comply_after_stage': self.comply_after_stage,
            'comply_delay': self.comply_delay,
            'actors': [{'id': a, 'x': flat[2 * i], 'y': flat[2 * i + 1]}
                       for i, a in enumerate(ids) if 2 * i + 1 < len(flat)],
            'clock': 'ros' if self.use_ros_clock else 'wall',
        }
        if self.mode == 'world':
            record.update(self.world_ground_truth())
        record.update(extra)
        msg = String()
        msg.data = json.dumps(record)
        self.gt_pub.publish(msg)

    def yolo_callback(self, msg):
        self.latest_yolo = msg
        self.latest_yolo_time = self.now_s()
        if self.mode == 'world':
            self.world_frame(msg)

    def fsm_callback(self, msg):
        try:
            state = json.loads(msg.data).get('state', '')
        except (ValueError, AttributeError):
            return
        if self.mode == 'world':
            self.world_fsm(state)
            return
        if state == self.comply_after_stage and self.comply_stage_time is None:
            self.comply_stage_time = self.now_s()
            self.publish_ground_truth('comply_trigger', fsm_state=state)
            self.get_logger().info(
                f'FSM reached {state}; simulated person will comply '
                f'in {self.comply_delay:.0f}s')

    def device_class(self):
        if self.scenario == 'vaping':
            return 'vape_device'
        if self.scenario == 'false_positive':
            return 'mobile_phone'
        if self.scenario in WORLD_DEVICE_CLASS:  # world-mode scenario types
            return WORLD_DEVICE_CLASS[self.scenario]
        return 'cigarette'

    def tick(self):
        if self.mode == 'off':
            return
        if self.mode == 'world':
            self.tick_world()
            return
        if self.start_time is None:
            if self.now_s() <= 0.0:
                return  # sim clock not running yet
            self.start_time = self.now_s()
        elapsed = self.now_s() - self.start_time
        scenario_active = elapsed >= self.start_delay
        self.publish_ground_truth('scenario_start')

        if self.scenario == 'target_loss':
            loss_after = self.get_parameter('target_loss_after').value
            if elapsed >= self.start_delay + loss_after:
                self.publish_ground_truth('target_removed')
                return  # person vanished entirely: pipeline must handle loss

        if (self.comply_stage_time is not None and not self.complied
                and self.now_s() - self.comply_stage_time >= self.comply_delay):
            self.complied = True
            self.get_logger().info('Simulated person complied (device removed)')
            self.publish_ground_truth('violation_cessation')

        now_gt = self.get_clock().now().nanoseconds * 1e-9
        if now_gt - self.gt_last_state >= 1.0:  # 1 Hz state heartbeat
            self.gt_last_state = now_gt
            self.publish_ground_truth(
                'state', once=False,
                device_present=scenario_active and not self.complied)

        array = Detection2DArray()
        array.header.stamp = self.get_clock().now().to_msg()
        array.header.frame_id = self.get_parameter('camera_frame').value

        now = self.now_s()
        yolo_fresh = (self.latest_yolo is not None
                      and now - self.latest_yolo_time < 1.0)
        use_augment = self.mode == 'augment' or (self.mode == 'auto' and yolo_fresh)

        person_box = None
        if use_augment and yolo_fresh:
            array.header = self.latest_yolo.header
            for det in self.latest_yolo.detections:
                array.detections.append(det)
                if det.results and det.results[0].hypothesis.class_id == 'person':
                    if person_box is None:
                        person_box = det.bbox
        if person_box is not None:
            self.last_person_box = person_box
            self.last_person_time = now
        else:
            if use_augment and self.mode == 'augment':
                self.det_pub.publish(array)  # pass-through only
                return
            coast = self.get_parameter('coast_duration').value
            if (self.last_person_box is not None
                    and now - self.last_person_time < coast):
                # YOLO dropout: coast on the last real position so the SORT
                # track survives instead of jumping to the synthetic pixel
                b = self.last_person_box
                person = make_detection(array.header, 'person', 0.85,
                                        b.center.position.x, b.center.position.y,
                                        b.size_x, b.size_y)
            else:
                # Synthetic person at the configured pixel
                px = self.get_parameter('person_pixel_x').value
                py = self.get_parameter('person_pixel_y').value
                pw = self.get_parameter('person_bbox_w').value
                ph = self.get_parameter('person_bbox_h').value
                person = make_detection(array.header, 'person', 0.92, px, py, pw, ph)
            array.detections.append(person)
            person_box = person.bbox

        if scenario_active and not self.complied:
            self.publish_ground_truth(
                'violation_onset' if self.is_violation() else 'confounder_onset')
            # Device near the mouth region: upper third of the person bbox
            mouth_x = person_box.center.position.x
            mouth_y = (person_box.center.position.y
                       - person_box.size_y / 2.0 + 0.18 * person_box.size_y)
            array.detections.append(make_detection(
                array.header, self.device_class(), 0.78,
                mouth_x + 8.0, mouth_y, 22.0, 12.0))
            if self.scenario in ('smoking', 'vaping'):
                array.detections.append(make_detection(
                    array.header, 'hand_mouth_gesture', 0.7,
                    mouth_x, mouth_y, 50.0, 40.0))
            if self.scenario == 'smoking':
                array.detections.append(make_detection(
                    array.header, 'smoke_vapour', 0.6,
                    mouth_x + 25.0, mouth_y - 30.0, 60.0, 50.0))

        self.det_pub.publish(array)

    # ======================================================== mode 'world'

    def init_world(self):
        p = self.declare_parameter
        p('comply_stage', 'S3_first')       # none | S1 | S3_first | S3_last
        p('comply_delay_s', 5.0)
        p('direct_warning_repeats', 3)      # which direct warning is "last"
        p('conf_jitter_sigma', 0.0)
        p('dropout_prob', 0.0)
        p('bbox_jitter_px', 0.0)
        p('device_score', 0.78)
        p('c7_device_score', 0.70)          # below the 0.75 C7 override
        p('brief_device_duration', 0.3)     # < 5 frames at 5 Hz YOLO
        p('brief_device_period', 6.0)
        p('target_loss_stage', '')          # e.g. APPROACH; '' = legacy timer
        p('target_loss_delay', 3.0)
        p('camera_pose', [5.8, 0.0, 2.5, 0.0, 0.55, 3.14159])
        p('camera_hfov', 1.3)
        p('person_height', 1.75)
        p('match_iou', 0.3)

        g = self.get_parameter
        self.camera = CameraModel(list(g('camera_pose').value), g('camera_hfov').value,
                                  g('image_width').value, g('image_height').value)
        self.noise = DetectionNoise(int(g('seed').value), g('conf_jitter_sigma').value,
                                    g('dropout_prob').value, g('bbox_jitter_px').value)
        self.layout = None
        self.violator = None
        self.model_poses = {}
        self.comply_time = None
        self.direct_count = 0
        self.fsm_state = 'MONITORING'
        self.loss_time = None
        self.violator_matched = False
        self.frame_stats = {'frames': 0, 'violator_matched': 0, 'injected': 0,
                            'dropped': 0}

        from gazebo_msgs.msg import ModelStates
        latched = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, '/compliance/actor_events',
                                 self.actor_event_callback, latched)
        self.create_subscription(ModelStates, '/gazebo/model_states',
                                 self.model_states_callback, 10)
        self.create_subscription(String, '/compliance/pa_warning',
                                 lambda m: self.warning_heard('S1'), 10)
        self.create_subscription(String, '/compliance/direct_warning',
                                 lambda m: self.warning_heard('S3'), 10)

    def actor_event_callback(self, msg):
        try:
            event = json.loads(msg.data)
        except ValueError:
            return
        if event.get('event') == 'layout':
            self.layout = event.get('persons', [])
            self.violator = event.get('violator')

    def model_states_callback(self, msg):
        for name, pose in zip(msg.name, msg.pose):
            self.model_poses[name] = (pose.position.x, pose.position.y)

    def world_fsm(self, state):
        if state != self.fsm_state:
            self.fsm_state = state
            stage = self.get_parameter('target_loss_stage').value
            if stage and state == stage and self.loss_time is None:
                self.loss_time = self.now_s() + \
                    self.get_parameter('target_loss_delay').value

    def warning_heard(self, kind):
        """The simulated person reacts to a warning it actually heard."""
        stage = self.get_parameter('comply_stage').value
        if kind == 'S3':
            self.direct_count += 1
        if self.comply_time is not None or not self.is_violation():
            return
        repeats = int(self.get_parameter('direct_warning_repeats').value)
        triggered = ((stage == 'S1' and kind == 'S1')
                     or (stage == 'S3_first' and kind == 'S3' and self.direct_count == 1)
                     or (stage == 'S3_last' and kind == 'S3'
                         and self.direct_count == repeats))
        if triggered:
            self.comply_time = self.now_s() + self.get_parameter('comply_delay_s').value
            self.publish_ground_truth('comply_trigger', warning=kind,
                                      direct_count=self.direct_count,
                                      comply_stage=stage)

    def world_ground_truth(self):
        record = {'comply_stage': self.get_parameter('comply_stage').value,
                  'comply_delay_s': self.get_parameter('comply_delay_s').value,
                  'violator': self.violator, 'layout': self.layout,
                  'fsm_state': self.fsm_state}
        if self.layout:
            record['actors'] = [
                {'id': a['actor'], 'role': a['role'],
                 'x': self.model_poses.get(a['actor'], (a['x'], a['y']))[0],
                 'y': self.model_poses.get(a['actor'], (a['x'], a['y']))[1]}
                for a in self.layout]
        pose = self.model_poses.get(self.violator)
        if pose is not None:
            record['violator_visible'] = self.camera.visible(
                pose[0], pose[1], self.get_parameter('person_height').value)
        record['frame_stats'] = dict(self.frame_stats)
        return record

    def tick_world(self):
        now = self.now_s()
        if self.start_time is None:
            if now <= 0.0 or self.layout is None:
                return  # sim clock / actor layout not ready yet
            self.start_time = now
        self.publish_ground_truth('scenario_start')
        elapsed = now - self.start_time
        if elapsed >= self.start_delay:
            self.publish_ground_truth('violation_onset' if self.is_violation()
                                      else 'confounder_onset')
        if self.comply_time is not None and not self.complied and now >= self.comply_time:
            self.complied = True
            self.get_logger().info('Simulated person complied (device removed)')
            self.publish_ground_truth('violation_cessation')
        legacy_loss = (self.scenario == 'target_loss'
                       and not self.get_parameter('target_loss_stage').value
                       and elapsed >= self.start_delay
                       + self.get_parameter('target_loss_after').value)
        if legacy_loss or (self.loss_time is not None and now >= self.loss_time):
            self.publish_ground_truth('target_removed')
        now_gt = self.get_clock().now().nanoseconds * 1e-9
        if now_gt - self.gt_last_state >= 1.0:
            self.gt_last_state = now_gt
            self.publish_ground_truth('state', once=False,
                                      device_present=self.device_active(elapsed))

    def device_active(self, elapsed):
        if self.start_time is None or elapsed < self.start_delay or self.complied:
            return False
        if self.scenario == 'walking':
            return False
        if self.scenario == 'brief_device':
            period = self.get_parameter('brief_device_period').value
            duration = self.get_parameter('brief_device_duration').value
            return (elapsed - self.start_delay) % period < duration
        return True

    def violator_box(self, persons):
        """YOLO person detection that is the violator (projection + IoU)."""
        pose = self.model_poses.get(self.violator)
        if pose is None:
            return None
        projected = self.camera.person_bbox(
            pose[0], pose[1], self.get_parameter('person_height').value)
        if projected is None:
            return None
        best, best_iou = None, self.get_parameter('match_iou').value
        for det in persons:
            b = det.bbox
            iou = box_iou((b.center.position.x, b.center.position.y, b.size_x, b.size_y),
                          projected)
            if iou >= best_iou:
                best, best_iou = det, iou
        return best

    def injections(self, box):
        """(class, score, cx, cy, w, h) attached to the violator's box,
        same geometry as the legacy injection."""
        cx, top, h = box.center.position.x, \
            box.center.position.y - box.size_y / 2.0, box.size_y
        mx, my = cx, top + 0.18 * h
        g = self.get_parameter
        device = g('device_score').value
        mouth = (mx + 8.0, my, 22.0, 12.0)
        kind = self.scenario
        out = []
        if kind in ('smoking', 'target_loss', 'brief_device'):
            out.append(('cigarette', device) + mouth)
        elif kind == 'vaping':
            out.append(('vape_device', device) + mouth)
        elif kind in ('phone', 'false_positive'):
            out.append(('mobile_phone', device) + mouth)
        elif kind in ('pen', 'straw'):
            out.append((kind, device) + mouth)
        elif kind == 'c7_conflict':
            out.append(('cigarette', g('c7_device_score').value) + mouth)
            out.append(('mobile_phone', device, mx - 10.0, my + 4.0, 20.0, 30.0))
        if kind in ('smoking', 'vaping'):
            out.append(('hand_mouth_gesture', 0.7, mx, my, 50.0, 40.0))
        if kind == 'smoking':
            out.append(('smoke_vapour', 0.6, mx + 25.0, my - 30.0, 60.0, 50.0))
        return out

    def world_frame(self, msg):
        if self.start_time is None:
            self.det_pub.publish(msg)  # scenario not started: pass-through
            return
        array = Detection2DArray()
        array.header = msg.header
        array.detections = list(msg.detections)
        persons = [d for d in msg.detections
                   if d.results and d.results[0].hypothesis.class_id == 'person']
        self.frame_stats['frames'] += 1
        elapsed = self.now_s() - self.start_time
        if self.device_active(elapsed):
            box = self.violator_box(persons)
            if box is not None:
                self.frame_stats['violator_matched'] += 1
                if self.noise.dropped():
                    self.frame_stats['dropped'] += 1
                else:
                    for cls, score, cx, cy, w, h in self.injections(box.bbox):
                        cx, cy, w, h = self.noise.box(cx, cy, w, h)
                        array.detections.append(make_detection(
                            array.header, cls, self.noise.score(score), cx, cy, w, h))
                    self.frame_stats['injected'] += 1
        self.det_pub.publish(array)


WORLD_VIOLATIONS = ('smoking', 'vaping', 'target_loss', 'c7_conflict')
WORLD_DEVICE_CLASS = {'phone': 'mobile_phone', 'pen': 'pen', 'straw': 'straw',
                      'walking': None}


def box_iou(a, b):
    """IoU of (cx, cy, w, h) boxes."""
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    union = a[2] * a[3] + b[2] * b[3] - iw * ih
    return iw * ih / union if union > 0 else 0.0


def main(args=None):
    rclpy.init(args=args)
    node = ScenarioPublisherNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
