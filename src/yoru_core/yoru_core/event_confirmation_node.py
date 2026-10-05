"""Event confirmation node (dissertation Sections 3.6 and 4.4).

Decision gate of the perception pipeline. Confirms a smoking/vaping event
only when the multi-criteria framework is satisfied:

  C1 person present (conf > 0.7)
  C2 cigarette or vape device (conf > 0.6)
  C3 spatial proximity: device overlaps the person's mouth region
  C4 temporal persistence: >= N consecutive frames
  C5 supporting evidence (optional): smoke_vapour / hand_mouth_gesture / hand_face
  C6 tracking consistency: same SORT track ID
  C7 false-positive risk: pen / mobile_phone / straw near mouth -> high risk

Confidence = w_D*device + w_P*proximity + w_T*persistence + w_S*support
(defaults 0.4 / 0.3 / 0.2 / 0.1, ROS parameters w_D, w_P, w_T, w_S)
Confirmed when Confidence >= confirm_confidence (0.6) AND C1 AND C2 AND C4
AND risk != high. uncertain_confidence (0.4) to 0.6 logged as 'uncertain';
below that discarded silently. The rule itself lives in confirmation_rule.py.
"""

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

from yoru_core import confirmation_rule as rule

DEVICE_CLASSES = ('cigarette', 'vape_device')
SUPPORT_WEIGHTS = {'smoke_vapour': 0.3, 'hand_mouth_gesture': 0.2, 'hand_face': 0.1}
CONFOUNDER_CLASSES = ('pen', 'mobile_phone', 'straw')


def bbox_iou(a, b):
    ax1 = a.center.position.x - a.size_x / 2.0
    ay1 = a.center.position.y - a.size_y / 2.0
    ax2 = a.center.position.x + a.size_x / 2.0
    ay2 = a.center.position.y + a.size_y / 2.0
    bx1 = b.center.position.x - b.size_x / 2.0
    by1 = b.center.position.y - b.size_y / 2.0
    bx2 = b.center.position.x + b.size_x / 2.0
    by2 = b.center.position.y + b.size_y / 2.0
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = a.size_x * a.size_y + b.size_x * b.size_y - inter
    return inter / union if union > 0.0 else 0.0


def in_mouth_region(person_bbox, obj_bbox, region_fraction=0.4):
    """True if the object's centre lies in the upper part of the person bbox."""
    px = person_bbox.center.position.x
    py_top = person_bbox.center.position.y - person_bbox.size_y / 2.0
    ox = obj_bbox.center.position.x
    oy = obj_bbox.center.position.y
    within_x = abs(ox - px) <= person_bbox.size_x * 0.75
    within_y = py_top <= oy <= py_top + person_bbox.size_y * region_fraction
    return within_x and within_y


class EventConfirmationNode(Node):

    def __init__(self):
        super().__init__('event_confirmation_node')

        self.declare_parameter('person_confidence', 0.7)
        self.declare_parameter('device_confidence', 0.6)
        self.declare_parameter('proximity_iou', 0.05)
        self.declare_parameter('persistence_frames', 5)
        self.declare_parameter('confirm_confidence',
                               rule.DEFAULT_CONFIRM_CONFIDENCE)
        self.declare_parameter('uncertain_confidence',
                               rule.DEFAULT_UNCERTAIN_CONFIDENCE)
        # Composite confidence weights (device, proximity, persistence,
        # support) - exposed for the sensitivity analysis
        for name, value in rule.DEFAULT_WEIGHTS.items():
            self.declare_parameter(name, value)
        self.declare_parameter('input_topic', '/compliance/tracked_detections')
        self.declare_parameter('output_topic', '/compliance/confirmed_events')
        # Which room/zone this camera observes; carried into metadata and incidents
        self.declare_parameter('room_id', '')
        # A specialist-model device this confident outranks a COCO confounder
        # (C7): a real cigarette isn't suppressed by a phone in the other hand
        self.declare_parameter('confounder_override_confidence', 0.75)
        # Soft vape hint: COCO sees vapes as 'cell phone'. A phone-like object
        # held AT THE MOUTH persistently is flagged as a possible vape on the
        # dashboard only - it never escalates (PA/robot/email) until the
        # trained vape_device model can actually confirm it.
        self.declare_parameter('vape_hint', True)
        # Evaluation instrumentation: one JSON record per tracked person per
        # frame (confirmed, uncertain AND rejected) for offline analysis
        self.declare_parameter('publish_debug', True)
        self.declare_parameter('debug_topic', '/compliance/confirmation_debug')

        self.persistence_required = int(self.get_parameter('persistence_frames').value)
        self.persistence = {}  # track_id -> consecutive satisfied frames
        self.phone_persistence = {}  # track_id -> consecutive phone-at-mouth frames

        self.confirmed_pub = self.create_publisher(
            Detection2DArray, self.get_parameter('output_topic').value, 10)
        self.metadata_pub = self.create_publisher(
            String, '/compliance/event_metadata', 10)
        self.debug_pub = None
        if self.get_parameter('publish_debug').value:
            self.debug_pub = self.create_publisher(
                String, self.get_parameter('debug_topic').value, 100)
        self.create_subscription(
            Detection2DArray, self.get_parameter('input_topic').value,
            self.tracked_callback, 10)

        weights = self.weights()
        self.get_logger().info(
            'Event confirmation node ready (criteria C1-C7, weights '
            + ', '.join(f'{k}={v:g}' for k, v in weights.items())
            + f', confirm>={self.get_parameter("confirm_confidence").value:g})')
        if abs(sum(weights.values()) - 1.0) > 1e-6:
            self.get_logger().warn(
                f'Confidence weights sum to {sum(weights.values()):g}, not 1')

    def publish_debug(self, header_stamp, track_id, record):
        """Full-precision record (no rounding) so offline analysis can
        recompute every decision exactly."""
        record = dict(record)
        record['stamp'] = header_stamp.sec + header_stamp.nanosec * 1e-9
        record['recv_stamp'] = self.get_clock().now().nanoseconds * 1e-9
        record['node'] = self.get_name()
        record['room'] = self.get_parameter('room_id').value
        record['track_id'] = track_id
        msg = String()
        msg.data = json.dumps(record)
        self.debug_pub.publish(msg)

    def weights(self):
        return {name: float(self.get_parameter(name).value)
                for name in rule.DEFAULT_WEIGHTS}

    def tracked_callback(self, msg):
        person_conf_min = self.get_parameter('person_confidence').value
        device_conf_min = self.get_parameter('device_confidence').value
        proximity_iou_min = self.get_parameter('proximity_iou').value
        confirm_at = self.get_parameter('confirm_confidence').value
        uncertain_at = self.get_parameter('uncertain_confidence').value
        weights = self.weights()

        persons, devices, supports, confounders = [], [], [], []
        for det in msg.detections:
            if not det.results:
                continue
            cls = det.results[0].hypothesis.class_id
            if cls == 'person':
                persons.append(det)
            elif cls in DEVICE_CLASSES:
                devices.append(det)
            elif cls in SUPPORT_WEIGHTS:
                supports.append(det)
            elif cls in CONFOUNDER_CLASSES:
                confounders.append(det)

        confirmed = Detection2DArray()
        confirmed.header = msg.header
        seen_tracks = set()

        for person in persons:
            track_id = person.id or 'untracked'
            seen_tracks.add(track_id)
            c1 = person.results[0].hypothesis.score > person_conf_min

            # C2 + C3: best device associated with this person's mouth region
            best_device, best_prox = None, 0.0
            for dev in devices:
                if dev.results[0].hypothesis.score <= device_conf_min:
                    continue
                iou_val = bbox_iou(person.bbox, dev.bbox)
                near_mouth = in_mouth_region(person.bbox, dev.bbox)
                if iou_val > proximity_iou_min or near_mouth:
                    prox = max(min(iou_val / 0.3, 1.0), 0.8 if near_mouth else 0.0)
                    if prox > best_prox:
                        best_device, best_prox = dev, prox
            c2 = best_device is not None
            c3 = best_prox > 0.0

            # C4 / C6: persistence on the same track ID. A missed frame
            # (hand motion blur, brief occlusion) decays the count instead
            # of zeroing it, so natural movement doesn't restart C4.
            if c1 and c2 and c3:
                self.persistence[track_id] = self.persistence.get(track_id, 0) + 1
            else:
                self.persistence[track_id] = max(
                    0, self.persistence.get(track_id, 0) - 1)
            frames = self.persistence[track_id]
            c4 = frames >= self.persistence_required
            persistence_score = min(frames / float(self.persistence_required), 1.0)

            # C5: supporting evidence near this person
            support_score = 0.0
            for sup in supports:
                if in_mouth_region(person.bbox, sup.bbox, region_fraction=0.6) or \
                        bbox_iou(person.bbox, sup.bbox) > 0.02:
                    support_score += SUPPORT_WEIGHTS[sup.results[0].hypothesis.class_id]
            support_score = min(support_score, 1.0)

            # C7: confounder near the mouth -> high false-positive risk
            fp_risk = 'low'
            confounder_class = None
            phone_at_mouth = False
            for con in confounders:
                if in_mouth_region(person.bbox, con.bbox):
                    fp_risk = 'high'
                    confounder_class = con.results[0].hypothesis.class_id
                    if con.results[0].hypothesis.class_id == 'mobile_phone':
                        phone_at_mouth = True
                    break

            device_score = best_device.results[0].hypothesis.score if c2 else 0.0
            confidence = rule.composite_confidence(
                device_score, best_prox, persistence_score, support_score,
                weights)

            # A high-confidence specialist detection outranks the confounder
            # guard: the cigarette model is far more trustworthy than COCO's
            # guess that something near the face is a phone/pen.
            override_at = self.get_parameter(
                'confounder_override_confidence').value
            fp_risk_raw = fp_risk
            if fp_risk == 'high' and c2 and device_score >= override_at:
                fp_risk = 'overridden'

            is_confirmed = rule.is_confirmed(confidence, c1, c2, c4, fp_risk,
                                             confirm_at)

            # Soft vape hint (dashboard only, never escalates): a phone-like
            # object held at the mouth for the persistence window
            if self.get_parameter('vape_hint').value and c1 \
                    and phone_at_mouth and not is_confirmed:
                self.phone_persistence[track_id] = \
                    self.phone_persistence.get(track_id, 0) + 1
            else:
                self.phone_persistence[track_id] = 0
            if self.phone_persistence.get(track_id, 0) \
                    >= self.persistence_required:
                hint = String()
                hint.data = json.dumps({
                    'track_id': track_id,
                    'room': self.get_parameter('room_id').value,
                    'status': 'possible_vape',
                    'confidence': None,
                    'event_class': 'possible_vape',
                })
                self.metadata_pub.publish(hint)
            status = rule.decision_status(is_confirmed, confidence,
                                          uncertain_at)

            if self.debug_pub is not None:
                self.publish_debug(msg.header.stamp, track_id, {
                    'D': device_score, 'P': best_prox,
                    'T': persistence_score, 'S': support_score,
                    'persistence_count': frames,
                    'persistence_required': self.persistence_required,
                    'C1': c1, 'C2': c2, 'C3': c3, 'C4': c4,
                    'C5': support_score > 0.0, 'C6': track_id != 'untracked',
                    'C7_fp_risk': fp_risk, 'fp_risk_raw': fp_risk_raw,
                    'confounder_class': confounder_class,
                    'person_score': person.results[0].hypothesis.score,
                    'device_class': (best_device.results[0].hypothesis.class_id
                                     if c2 else None),
                    'C': confidence, 'decision': status,
                    'weights': weights, 'confirm_confidence': confirm_at,
                    'uncertain_confidence': uncertain_at,
                    'override_confidence': override_at,
                })

            if is_confirmed:
                event = person  # person detection carries the track ID and bbox
                confirmed.detections.append(event)

            if status != 'rejected':
                meta = String()
                meta.data = json.dumps({
                    'track_id': track_id,
                    'room': self.get_parameter('room_id').value,
                    'status': status,
                    'confidence': round(confidence, 3),
                    'event_class': (best_device.results[0].hypothesis.class_id
                                    if c2 else None),
                    'criteria': {
                        'C1_person': c1, 'C2_device': c2, 'C3_proximity': c3,
                        'C4_persistence': c4, 'C5_support': round(support_score, 2),
                        'C6_track': track_id != 'untracked',
                        'C7_fp_risk': fp_risk,
                    },
                    'scores': {
                        'device': round(device_score, 3),
                        'proximity': round(best_prox, 3),
                        'persistence': round(persistence_score, 3),
                        'support': round(support_score, 3),
                    },
                })
                self.metadata_pub.publish(meta)

        # Forget tracks that disappeared (volatile, privacy-preserving)
        for stale in [t for t in self.persistence if t not in seen_tracks]:
            del self.persistence[stale]
        for stale in [t for t in self.phone_persistence
                      if t not in seen_tracks]:
            del self.phone_persistence[stale]

        if confirmed.detections:
            self.confirmed_pub.publish(confirmed)


def main(args=None):
    rclpy.init(args=args)
    node = EventConfirmationNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
