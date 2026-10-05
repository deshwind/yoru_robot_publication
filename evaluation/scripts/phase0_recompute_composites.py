#!/usr/bin/env python3
"""Phase 0 evidence: recompute D, P, T, S and C for the injected scenarios.

Runs the real EventConfirmationNode callback (default parameters) on the
exact detections scenario_publisher_node injects for Scenarios A, A-V and C,
frame by frame, and prints each term and the decision. Also prints
C - w_P*P, the quantity matching the dissertation figure's printed totals.

Usage (ROS 2 sourced, from the repo root):
  PYTHONPATH=src/yoru_core:$PYTHONPATH python3 evaluation/scripts/phase0_recompute_composites.py
"""

import json

import rclpy
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

from yoru_core.event_confirmation_node import EventConfirmationNode

# yoru_sim.yaml scenario_publisher_node geometry
PX, PY, PW, PH = 320.0, 240.0, 60.0, 150.0
DEVICE_SCORE = 0.78


class Capture:
    def __init__(self):
        self.msgs = []

    def publish(self, msg):
        self.msgs.append(msg)


def det(cls, score, cx, cy, w, h, track_id=''):
    d = Detection2D()
    d.id = track_id
    d.bbox.center.position.x = float(cx)
    d.bbox.center.position.y = float(cy)
    d.bbox.size_x = float(w)
    d.bbox.size_y = float(h)
    hyp = ObjectHypothesisWithPose()
    hyp.hypothesis.class_id = cls
    hyp.hypothesis.score = float(score)
    d.results.append(hyp)
    return d


def injected_frame(scenario):
    """Mirror of scenario_publisher_node.tick() for a synthetic person."""
    mx, my = PX, PY - PH / 2.0 + 0.18 * PH
    device = 'vape_device' if scenario == 'vaping' else 'cigarette'
    frame = Detection2DArray()
    frame.detections = [det('person', 0.92, PX, PY, PW, PH, 'c1_1000'),
                        det(device, DEVICE_SCORE, mx + 8.0, my, 22.0, 12.0)]
    if scenario in ('smoking', 'vaping'):
        frame.detections.append(det('hand_mouth_gesture', 0.7, mx, my, 50.0, 40.0))
    if scenario == 'smoking':
        frame.detections.append(det('smoke_vapour', 0.6, mx + 25.0, my - 30.0, 60.0, 50.0))
    return frame


def main():
    rclpy.init()
    print('scenario      frame  D      P      T      S      C      C-0.3P  status')
    for label, scenario in (('A smoking', 'smoking'), ('A-V vaping', 'vaping'),
                            ('C target_loss', 'target_loss')):
        node = EventConfirmationNode()
        node.metadata_pub, node.confirmed_pub = Capture(), Capture()
        for frame_no in range(1, 7):
            node.tracked_callback(injected_frame(scenario))
            meta = json.loads(node.metadata_pub.msgs[-1].data)
            s = meta['scores']
            print(f'{label:13s} {frame_no:5d}  {s["device"]:.3f}  {s["proximity"]:.3f}  '
                  f'{s["persistence"]:.3f}  {s["support"]:.3f}  {meta["confidence"]:.3f}  '
                  f'{meta["confidence"] - 0.3 * s["proximity"]:.3f}   {meta["status"]}')
        node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
