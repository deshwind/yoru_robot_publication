#!/usr/bin/env python3
"""Phase 2 evidence: replay every recorded /compliance/confirmation_debug
record through confirmation_rule and compare with the online decision.

Also reports the header-stamp vs receive-stamp lag, which decides which
timestamp the Phase 5 metrics must use.

Usage (ROS 2 sourced, repo root):
  PYTHONPATH=src/yoru_core:$PYTHONPATH python3 evaluation/scripts/phase2_replay_check.py <bag_dir>
"""

import collections
import json
import statistics
import sys

import rosbag2_py
from rclpy.serialization import deserialize_message
from std_msgs.msg import String

from yoru_core import confirmation_rule as rule


def debug_records(bag_dir):
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=bag_dir, storage_id='sqlite3'),
                rosbag2_py.ConverterOptions('cdr', 'cdr'))
    reader.set_filter(rosbag2_py.StorageFilter(
        topics=['/compliance/confirmation_debug']))
    while reader.has_next():
        _, raw, _ = reader.read_next()
        yield json.loads(deserialize_message(raw, String).data)


def main(bag_dir):
    total, mismatches = 0, []
    decisions = collections.Counter()
    lag = []
    for r in debug_records(bag_dir):
        total += 1
        c = rule.composite_confidence(r['D'], r['P'], r['T'], r['S'], r['weights'])
        confirmed = rule.is_confirmed(c, r['C1'], r['C2'], r['C4'], r['C7_fp_risk'],
                                      r['confirm_confidence'])
        offline = rule.decision_status(confirmed, c, r['uncertain_confidence'])
        decisions[(r['node'], offline)] += 1
        if c != r['C'] or offline != r['decision']:
            mismatches.append((r, c, offline))
        lag.append(r['recv_stamp'] - r['stamp'])
    print(f'debug records replayed: {total}')
    print(f'exact matches (C bit-identical and same decision): {total - len(mismatches)}')
    print(f'mismatches: {len(mismatches)}')
    for (node, decision), n in sorted(decisions.items()):
        print(f'  {n:6d}  {node}  {decision}')
    if lag:
        print(f'\nheader stamp -> node receive lag (s): median {statistics.median(lag):.3f}, '
              f'min {min(lag):.3f}, max {max(lag):.3f}')


if __name__ == '__main__':
    main(sys.argv[1])
