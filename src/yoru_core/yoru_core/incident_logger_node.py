"""Incident logger node (dissertation Section 4.8).

Privacy-preserving incident logging: metadata only (timestamp, room ID,
approximate coordinates, confidence, escalation stage). No video, audio,
facial or biometric data is ever written (GDPR / privacy-by-design,
Section 3.11). JSON Lines format with size-based rotation and
retention-based cleanup.
"""

import json
import os
import time
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class IncidentLoggerNode(Node):

    def __init__(self):
        super().__init__('incident_logger_node')

        self.declare_parameter('log_dir', os.path.expanduser('~/compliance_robot_logs'))
        self.declare_parameter('room_id', 'sim_room_1')
        self.declare_parameter('retention_days', 30)
        self.declare_parameter('max_log_size_mb', 10.0)

        self.log_dir = self.get_parameter('log_dir').value
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, 'incidents.jsonl')
        self.cleanup_old_logs()

        self.latest_target = {'x': None, 'y': None}
        # Evaluation instrumentation: latched path of the incident log so a
        # recorded bag can always be matched to its JSONL file
        from rclpy.qos import DurabilityPolicy, QoSProfile
        path_pub = self.create_publisher(
            String, '/compliance/incident_log_path',
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        path_msg = String()
        path_msg.data = os.path.abspath(self.log_path)
        path_pub.publish(path_msg)
        self.path_pub = path_pub
        self.create_subscription(String, '/compliance/incident_log',
                                 self.incident_callback, 10)
        from geometry_msgs.msg import PoseStamped
        self.create_subscription(PoseStamped, '/compliance/navigation_targets',
                                 self.target_callback, 10)

        self.get_logger().info(f'Incident logger ready -> {self.log_path}')

    def target_callback(self, msg):
        self.latest_target = {
            'x': round(msg.pose.position.x, 2),
            'y': round(msg.pose.position.y, 2),
        }

    def incident_callback(self, msg):
        try:
            incident = json.loads(msg.data)
        except ValueError:
            incident = {'raw': msg.data}

        record = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'room_id': incident.get('room') or self.get_parameter('room_id').value,
            'approx_location': self.latest_target,
        }
        record.update(incident)

        self.rotate_if_needed()
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
        self.get_logger().info(
            f'Incident logged: stage={record.get("stage_reached")} '
            f'outcome={record.get("outcome")} track={record.get("track_id")}')

    def rotate_if_needed(self):
        max_bytes = self.get_parameter('max_log_size_mb').value * 1024 * 1024
        if os.path.isfile(self.log_path) and os.path.getsize(self.log_path) > max_bytes:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            os.rename(self.log_path,
                      os.path.join(self.log_dir, f'incidents_{stamp}.jsonl'))

    def cleanup_old_logs(self):
        retention_s = self.get_parameter('retention_days').value * 86400
        now = time.time()
        for name in os.listdir(self.log_dir):
            path = os.path.join(self.log_dir, name)
            if name.endswith('.jsonl') and now - os.path.getmtime(path) > retention_s:
                os.remove(path)
                self.get_logger().info(f'Retention cleanup: removed {name}')


def main(args=None):
    rclpy.init(args=args)
    node = IncidentLoggerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
