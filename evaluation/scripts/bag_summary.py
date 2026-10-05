#!/usr/bin/env python3
"""Summarise an evaluation bag: per-topic counts, FSM transitions, warnings,
ground-truth events, confirmation decisions and the real-time factor.

Uses rosbag2_py (ships with ROS 2 Humble); the Phase 5 metrics extractor
uses the `rosbags` library instead, as specified.

Usage: python3 evaluation/scripts/bag_summary.py <bag_dir>
"""

import collections
import json
import sys

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

JSON_TOPICS = ('/compliance/fsm_state', '/compliance/audio_event',
               '/compliance/scenario_ground_truth',
               '/compliance/confirmation_debug', '/compliance/incident_log',
               '/compliance/nav_status', '/compliance/incident_log_path',
               '/compliance/actor_events')
PEOPLE = ('person_1', 'person_2', 'person_3', 'intruder_1')


def read(bag_dir):
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=bag_dir, storage_id='sqlite3'),
                rosbag2_py.ConverterOptions('cdr', 'cdr'))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    while reader.has_next():
        topic, raw, t_recv = reader.read_next()
        yield topic, types[topic], raw, t_recv


def main(bag_dir):
    counts = collections.Counter()
    types = {}
    json_msgs = collections.defaultdict(list)
    clock = []          # (wall receive ns, sim s)
    model_names = set()
    tracks = collections.defaultdict(list)   # model -> [(sim s, x, y)]
    scan_min = (float('inf'), None)          # (range, sim s)
    sim_now = 0.0
    for topic, type_name, raw, t_recv in read(bag_dir):
        counts[topic] += 1
        types[topic] = type_name
        if topic in JSON_TOPICS:
            data = deserialize_message(raw, get_message(type_name)).data
            try:
                json_msgs[topic].append(json.loads(data))
            except ValueError:
                json_msgs[topic].append({'raw': data})
        elif topic == '/clock':
            msg = deserialize_message(raw, get_message(type_name))
            sim_now = msg.clock.sec + msg.clock.nanosec * 1e-9
            if counts[topic] % 50 == 1:
                clock.append((t_recv, sim_now))
        elif topic == '/gazebo/model_states':
            msg = deserialize_message(raw, get_message(type_name))
            model_names.update(msg.name)
            for name, pose in zip(msg.name, msg.pose):
                if name in PEOPLE or name == 'yoru_robot':
                    tracks[name].append((sim_now, pose.position.x, pose.position.y))
        elif topic == '/scan':
            msg = deserialize_message(raw, get_message(type_name))
            valid = [r for r in msg.ranges if msg.range_min < r < msg.range_max]
            if valid and min(valid) < scan_min[0]:
                scan_min = (min(valid), sim_now)

    print(f'bag: {bag_dir}\n\n== topics (messages, type)')
    for topic in sorted(counts):
        print(f'  {counts[topic]:7d}  {topic}  [{types[topic]}]')

    if len(clock) > 1:
        wall = (clock[-1][0] - clock[0][0]) * 1e-9
        sim = clock[-1][1] - clock[0][1]
        print(f'\n== real-time factor: {sim:.1f} s sim / {wall:.1f} s wall '
              f'= {sim / wall:.3f}')
    if model_names:
        print(f'\n== gazebo models: {sorted(model_names)}')

    print('\n== actor events (/compliance/actor_events)')
    for e in json_msgs['/compliance/actor_events']:
        extra = {k: v for k, v in e.items()
                 if k not in ('stamp', 'event', 'seed', 'scenario_type', 'violator')}
        print(f'  t={e["stamp"]:8.2f}  {e["event"]:<18s} {json.dumps(extra)}')

    inside = {n: t for n, t in tracks.items()
              if n == 'yoru_robot' or any(abs(x) < 6 and abs(y) < 4 for _, x, y in t)}
    if inside:
        print('\n== positions in the building (every ~10 s sim)')
        for name, t in sorted(inside.items()):
            samples, last = [], -1e9
            for ts, x, y in t:
                if ts - last >= 10.0:
                    samples.append(f'{ts:.0f}s({x:.2f},{y:.2f})')
                    last = ts
            print(f'  {name:11s} ' + ' '.join(samples))
        robot = tracks.get('yoru_robot', [])
        for name, t in sorted(inside.items()):
            if name == 'yoru_robot' or not robot:
                continue
            by_time = {round(ts, 1): (x, y) for ts, x, y in t}
            best = (float('inf'), None)
            for ts, rx, ry in robot:
                p = by_time.get(round(ts, 1))
                if p and abs(p[0]) < 6 and abs(p[1]) < 4:
                    d = ((p[0] - rx) ** 2 + (p[1] - ry) ** 2) ** 0.5
                    if d < best[0]:
                        best = (d, ts)
            if best[1] is not None:
                print(f'  min robot-{name} centre distance: {best[0]:.2f} m at t={best[1]:.1f}')
    if scan_min[1] is not None:
        print(f'  min lidar range: {scan_min[0]:.3f} m at t={scan_min[1]:.1f}')

    print('\n== FSM transitions (/compliance/fsm_state)')
    for e in json_msgs['/compliance/fsm_state']:
        print(f'  t={e["stamp"]:8.2f}  {e["previous_state"]:>14s} -> '
              f'{e["new_state"]:<14s} reason={e["reason"]:<20s} '
              f'track={e["track_id"]} room={e["room"]} '
              f'stage={e["stage_reached"]} in_state={e.get("time_in_state")}')

    print('\n== audio events (/compliance/audio_event)')
    for e in json_msgs['/compliance/audio_event']:
        print(f'  t={e["stamp"]:8.2f}  {e["kind"]:<15s} backend={e["backend"]} '
              f'track={e["track_id"]} room={e["room"]}')

    print('\n== ground truth (/compliance/scenario_ground_truth, non-heartbeat)')
    gt = json_msgs['/compliance/scenario_ground_truth']
    for e in gt:
        if e.get('event') != 'state':
            print(f'  t={e["stamp"]:8.2f}  {e["event"]:<20s} '
                  f'scenario={e["scenario_type"]} seed={e["seed"]} '
                  f'violator={e.get("violator")} actors={e["actors"]}')
    states = [e for e in gt if e.get('event') == 'state']
    if states and 'frame_stats' in states[-1]:
        print(f'  last frame_stats: {states[-1]["frame_stats"]}')
    print(f'  ({sum(1 for e in gt if e.get("event") == "state")} heartbeat messages)')

    debug = json_msgs['/compliance/confirmation_debug']
    print(f'\n== confirmation debug records: {len(debug)}')
    by = collections.Counter((d['node'], d['decision']) for d in debug)
    for key, n in sorted(by.items()):
        print(f'  {n:6d}  {key}')
    first = next((d for d in debug if d['decision'] == 'confirmed'), None)
    if first:
        print('  first confirmed record: ' + json.dumps(
            {k: first[k] for k in ('stamp', 'node', 'track_id', 'D', 'P', 'T', 'S',
                                   'C', 'persistence_count', 'C1', 'C2', 'C4',
                                   'C7_fp_risk')}))

    print('\n== nav status')
    for e in json_msgs['/compliance/nav_status']:
        print(f'  {e}')
    print('\n== incident log')
    for e in json_msgs['/compliance/incident_log']:
        print(f'  {e}')
    print(f'\n== incident log path: {json_msgs["/compliance/incident_log_path"]}')


if __name__ == '__main__':
    main(sys.argv[1])
