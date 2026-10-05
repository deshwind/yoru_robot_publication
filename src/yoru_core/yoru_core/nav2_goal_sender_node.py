"""Nav2 goal sender node (dissertation Section 4.6).

Safety-conscious bridge between the coordinate transform node and Nav2.
Only acts while the FSM is in APPROACH. Protective mechanisms:

  - safe standoff: goal is offset 'safe_stopping_distance' short of the person
  - goal cooldown between successive navigation goals
  - goal timeout with automatic cancellation
  - cancels immediately when the FSM leaves APPROACH
"""

import json
import math
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String
from tf2_ros import Buffer, TransformListener


class Nav2GoalSenderNode(Node):

    def __init__(self):
        super().__init__('nav2_goal_sender_node')

        self.declare_parameter('safe_stopping_distance', 1.5)
        self.declare_parameter('goal_cooldown', 10.0)
        self.declare_parameter('goal_timeout', 60.0)
        self.declare_parameter('target_max_age', 5.0)
        self.declare_parameter('robot_base_frame', 'base_link')
        # false: wall clock (as deployed); true: node clock (sim time)
        self.declare_parameter('use_ros_clock', False)
        self.use_ros_clock = bool(self.get_parameter('use_ros_clock').value)

        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.fsm_state = 'MONITORING'
        self.latest_target = None
        self.latest_target_time = 0.0
        self.goal_handle = None
        self.navigating = False
        self.goal_sent_time = 0.0
        self.last_goal_time = 0.0

        self.status_pub = self.create_publisher(String, '/compliance/nav_status', 10)
        self.create_subscription(
            PoseStamped, '/compliance/navigation_targets', self.target_callback, 10)
        self.create_subscription(
            String, '/compliance/fsm_status', self.fsm_callback, 10)
        self.create_timer(0.5, self.tick)

        self.get_logger().info('Nav2 goal sender ready (waits for FSM APPROACH)')

    def now_s(self):
        if self.use_ros_clock:
            return self.get_clock().now().nanoseconds * 1e-9
        return time.monotonic()

    def publish_status(self, state, **extra):
        msg = String()
        payload = {'state': state}
        payload.update(extra)
        msg.data = json.dumps(payload)
        self.status_pub.publish(msg)

    def target_callback(self, msg):
        self.latest_target = msg
        self.latest_target_time = self.now_s()

    def fsm_callback(self, msg):
        try:
            self.fsm_state = json.loads(msg.data).get('state', self.fsm_state)
        except ValueError:
            return

    def robot_xy(self):
        base = self.get_parameter('robot_base_frame').value
        try:
            tf = self.tf_buffer.lookup_transform('map', base, rclpy.time.Time())
            return tf.transform.translation.x, tf.transform.translation.y
        except Exception:  # noqa: BLE001 - TF not available yet
            return None

    def tick(self):
        now = self.now_s()

        if self.navigating:
            if self.fsm_state != 'APPROACH':
                self.cancel_goal('fsm_left_approach')
            elif now - self.goal_sent_time > self.get_parameter('goal_timeout').value:
                self.cancel_goal('timeout')
                self.publish_status('timeout')
            return

        if self.fsm_state != 'APPROACH':
            return
        if self.latest_target is None or \
                now - self.latest_target_time > self.get_parameter('target_max_age').value:
            return
        if now - self.last_goal_time < self.get_parameter('goal_cooldown').value:
            return

        robot = self.robot_xy()
        if robot is None:
            self.get_logger().warn('No map->base_link TF yet; cannot send goal')
            return

        tx = self.latest_target.pose.position.x
        ty = self.latest_target.pose.position.y
        rx, ry = robot
        dist = math.hypot(tx - rx, ty - ry)
        standoff = self.get_parameter('safe_stopping_distance').value

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()

        if standoff <= 0.0:
            # Camera-spot mode (Yoru V2): the target IS the marked standing
            # spot - drive exactly there and face the marked direction.
            if dist <= 0.25:
                self.publish_status('succeeded', note='already_at_spot')
                self.last_goal_time = now
                return
            gx, gy = tx, ty
            goal.pose.pose.orientation = self.latest_target.pose.orientation
        else:
            # Person-position mode: stop 'standoff' metres short of the target
            if dist <= standoff:
                # Already within the social standoff distance: report success
                self.publish_status('succeeded', note='already_within_standoff')
                self.last_goal_time = now
                return
            ratio = (dist - standoff) / dist
            gx = rx + (tx - rx) * ratio
            gy = ry + (ty - ry) * ratio
            heading = math.atan2(ty - gy, tx - gx)
            goal.pose.pose.orientation.z = math.sin(heading / 2.0)
            goal.pose.pose.orientation.w = math.cos(heading / 2.0)

        goal.pose.pose.position.x = gx
        goal.pose.pose.position.y = gy

        if not self.nav_client.wait_for_server(timeout_sec=1.0):
            self.get_logger().warn('Nav2 action server not available')
            self.publish_status('nav2_unavailable')
            return

        self.get_logger().info(
            f'Approach goal ({gx:.2f},{gy:.2f}), standoff {standoff:.1f} m '
            f'from target ({tx:.2f},{ty:.2f})')
        self.navigating = True
        self.goal_sent_time = now
        self.last_goal_time = now
        self.publish_status('navigating', goal={'x': gx, 'y': gy})
        future = self.nav_client.send_goal_async(goal)
        future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        self.goal_handle = future.result()
        if not self.goal_handle or not self.goal_handle.accepted:
            self.navigating = False
            self.publish_status('rejected')
            return
        result_future = self.goal_handle.get_result_async()
        result_future.add_done_callback(self.result_callback)

    def result_callback(self, future):
        self.navigating = False
        status = future.result().status
        if status == 4:  # SUCCEEDED
            self.publish_status('succeeded')
        elif status == 5:  # CANCELED
            self.publish_status('cancelled')
        else:
            self.publish_status('aborted', code=int(status))

    def cancel_goal(self, reason):
        self.get_logger().info(f'Cancelling navigation goal ({reason})')
        if self.goal_handle is not None:
            self.goal_handle.cancel_goal_async()
        self.navigating = False


def main(args=None):
    rclpy.init(args=args)
    node = Nav2GoalSenderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
