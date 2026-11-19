#!/usr/bin/env python3
"""Pictures of a running simulation, for documentation and figures only.

Attaches to a running simulation on a ROS domain and saves PNG snapshots of
every camera at each escalation-stage change (/compliance/fsm_state) and,
optionally, at given sim times. With --overview it first spawns two extra
static cameras looking over the building (top-down and oblique) so the scene
itself can be shown.

A run with this script attached is NOT an evaluation run: the extra subscribers
(and, with --overview, two extra rendering cameras) add load. Use a separate
run tag (e.g. doc_pictures) so such runs never enter the metrics.

  # terminal 1: one run (the runner uses domain 61 for its first run, attempt 1)
  python3 evaluation/scripts/run_batch.py --scenarios A --seed-list 0 --tag doc_pictures \\
      --out evaluation/data/doc --manifest evaluation/data/doc/manifest.csv
  # terminal 2:
  python3 evaluation/scripts/capture_pictures.py --domain 61 --overview \\
      --out evidence/pictures/A_seed0

Writes <out>/<NN>_<sim time>s_<stage>__<camera>.png and <out>/index.csv.
"""

import argparse
import csv
import json
import os
import sys
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String

CAMERAS = {
    'cctv1_raw': '/cctv1/image_raw',
    'cctv2_raw': '/cctv2/image_raw',
    'cctv1_yolo': '/compliance/cctv1/debug_image',
    'cctv2_yolo': '/compliance/cctv2/debug_image',
    'robot_camera': '/camera/image_raw',
}
OVERVIEW = {
    # name: (x, y, z, roll, pitch, yaw, horizontal FOV rad, width, height)
    'overview_top': (0.0, 0.0, 13.0, 0.0, 1.5708, 1.5708, 1.0, 1280, 853),
    'overview_oblique': (0.0, -9.5, 11.0, 0.0, 0.85, 1.5708, 1.05, 1280, 720),
}


def overview_sdf(name, pose):
    x, y, z, r, p, yw, fov, w, h = pose
    return f"""<?xml version="1.0"?>
<sdf version="1.6">
  <model name="doc_{name}">
    <static>true</static>
    <pose>{x} {y} {z} {r} {p} {yw}</pose>
    <link name="link">
      <sensor name="{name}" type="camera">
        <update_rate>1.0</update_rate>
        <camera>
          <horizontal_fov>{fov}</horizontal_fov>
          <image><width>{w}</width><height>{h}</height><format>R8G8B8</format></image>
          <clip><near>0.1</near><far>60</far></clip>
        </camera>
        <plugin name="{name}_plugin" filename="libgazebo_ros_camera.so">
          <ros><namespace>/doc</namespace></ros>
          <camera_name>{name}</camera_name>
          <frame_name>doc_{name}</frame_name>
        </plugin>
      </sensor>
    </link>
  </model>
</sdf>"""


class Capture(Node):
    def __init__(self, cli):
        super().__init__('doc_picture_capture',
                         parameter_overrides=[Parameter('use_sim_time', value=True)])
        self.cli = cli
        self.bridge = CvBridge()
        self.latest = {}
        self.state = None
        self.count = 0
        self.at = sorted(cli.at)
        os.makedirs(cli.out, exist_ok=True)
        self.index = open(os.path.join(cli.out, 'index.csv'), 'w', newline='')
        self.writer = csv.writer(self.index)
        self.writer.writerow(['file', 'sim_time_s', 'trigger', 'stage', 'camera', 'topic'])
        cameras = dict(CAMERAS)
        if cli.overview:
            for name in OVERVIEW:
                cameras[name] = f'/doc/{name}/image_raw'
        for name, topic in cameras.items():
            self.create_subscription(Image, topic, self._keep(name), qos_profile_sensor_data)
        self.topics = cameras
        self.create_subscription(String, '/compliance/fsm_state', self.on_state, 10)
        self.create_timer(0.2, self.on_timer)

    def _keep(self, name):
        def cb(msg):
            self.latest[name] = msg
        return cb

    def sim_now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def on_state(self, msg):
        # /compliance/fsm_state is a JSON event published on each transition
        try:
            event = json.loads(msg.data)
        except ValueError:
            return
        new = event.get('new_state', '')
        if new and new != self.state:
            self.state = new
            self.snapshot(f"{event.get('previous_state')} -> {new} ({event.get('reason')})")

    def on_timer(self):
        while self.at and self.sim_now() >= self.at[0]:
            t = self.at.pop(0)
            self.snapshot(f'at {t:g} s')

    def snapshot(self, trigger):
        t = self.sim_now()
        self.count += 1
        stage = (self.state or 'START').replace('/', '-')
        saved = 0
        for name, msg in sorted(self.latest.items()):
            img = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
            fname = f'{self.count:02d}_{t:06.1f}s_{stage}__{name}.png'
            cv2.imwrite(os.path.join(self.cli.out, fname), img)
            self.writer.writerow([fname, f'{t:.1f}', trigger, self.state, name, self.topics[name]])
            saved += 1
        self.index.flush()
        self.get_logger().info(f'{trigger} at sim {t:.1f} s: {saved} pictures')


def spawn_overview(node, timeout):
    from gazebo_msgs.srv import SpawnEntity
    client = node.create_client(SpawnEntity, '/spawn_entity')
    if not client.wait_for_service(timeout_sec=timeout):
        node.get_logger().error('/spawn_entity not available: no overview cameras')
        return
    for name, pose in OVERVIEW.items():
        req = SpawnEntity.Request()
        req.name = f'doc_{name}'
        req.xml = overview_sdf(name, pose)
        future = client.call_async(req)
        rclpy.spin_until_future_complete(node, future, timeout_sec=30)
        result = future.result()
        node.get_logger().info(f'spawn {name}: {result.status_message if result else "no reply"}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--domain', type=int, required=True, help='ROS_DOMAIN_ID of the run')
    ap.add_argument('--out', required=True, help='output folder for the PNGs')
    ap.add_argument('--overview', action='store_true', help='spawn two overview cameras')
    ap.add_argument('--at', type=float, nargs='*', default=[], help='extra sim times (s)')
    ap.add_argument('--wait', type=float, default=240.0,
                    help='wall seconds to wait for the simulation to appear')
    ap.add_argument('--max-wall', type=float, default=900.0, help='stop after this many wall s')
    cli = ap.parse_args()
    os.environ['ROS_DOMAIN_ID'] = str(cli.domain)
    rclpy.init()
    node = Capture(cli)
    if cli.overview:
        spawn_overview(node, cli.wait)
    start = time.monotonic()
    seen_clock = False
    last_clock = None
    try:
        while time.monotonic() - start < cli.max_wall:
            rclpy.spin_once(node, timeout_sec=0.2)
            now = node.sim_now()
            if now > 0:
                if now != last_clock:
                    last_clock, last_change = now, time.monotonic()
                    seen_clock = True
                elif seen_clock and time.monotonic() - last_change > 15:
                    break          # the simulation has stopped
    except KeyboardInterrupt:
        pass
    node.snapshot('end')
    node.index.close()
    print(f'{node.count} snapshots -> {cli.out}')
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
