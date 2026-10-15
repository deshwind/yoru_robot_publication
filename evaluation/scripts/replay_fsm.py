#!/usr/bin/env python3
"""Replay recorded runs through the real compliance FSM node.

Each run's recorded FSM inputs are fed, in the order the bag recorder
received them, to `ComplianceFsmNode` (the deployed class, not a copy) on a
simulated clock: the clock takes each recorded /clock value and the node ticks
once per value (its 10 Hz timer on sim time). The node gets the run's own
parameters (yoru_sim.yaml, then the run's overlay.yaml) plus the variant under
test.

Inputs from the bag: /compliance/cctvN/confirmed, /compliance/event_metadata,
/compliance/nav_status, /scan, /compliance/autonomy_paused. The per-camera
frame topic that the variants use is not in the baseline bags. Frames are
rebuilt from /compliance/confirmation_debug, which has one record per tracked
person per frame, so a frame in which no person was tracked is missing (the
offline analysis counts it from the 1 Hz frame_stats heartbeat instead).

Checks (written to <outdir>/report.md):
 1. Default parameters reproduce the logged FSM: the same transitions with
    the same reasons, at times within 0.15 s.
 2. sustained_confirmation_ratio = 0.6: escalation and S1 time against
    (a) offline_extensions.escalation_times on the same rebuilt frames
        (identical inputs: tests the implementation), and
    (b) the published offline result (sustained_events.csv, heartbeat
        frame counts).
 3. compliance_aware_approach (hold_s1, reset_first, both): open-loop outcome
    per scenario. After the first decision that differs from the logged run,
    the recorded inputs (robot motion, scan, navigation) no longer follow
    from the replayed decisions, so this is a preview, not a result.

Usage: python3 evaluation/scripts/replay_fsm.py [--manifest M] [--tag baseline]
       [--runs baseline/H/0,...] [--outdir evaluation/results/fsm_replay]
"""

import argparse
import collections
import glob
import json
import math
import os
import sys
import types

import numpy as np
import pandas as pd
import yaml
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_types_from_msg, get_typestore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'yoru_core'))
sys.path.insert(0, os.path.join(ROOT, 'evaluation', 'scripts'))

import rclpy  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402

from yoru_core.compliance_fsm_node import ComplianceFsmNode  # noqa: E402
import offline_extensions as ox  # noqa: E402

SIM_YAML = os.path.join(ROOT, 'src', 'yoru_bringup', 'config', 'yoru_sim.yaml')
FRAME_TOPICS = ['/replay/cctv1/tracked', '/replay/cctv2/tracked']
INPUTS = ['/clock', '/compliance/cctv1/confirmed', '/compliance/cctv2/confirmed',
          '/compliance/event_metadata', '/compliance/nav_status', '/scan',
          '/compliance/autonomy_paused', '/compliance/confirmation_debug',
          '/compliance/fsm_state']
VARIANTS = {
    'default': {},
    'sustained_0.6': {'sustained_confirmation_ratio': 0.6},
    'hold_s1': {'compliance_aware_approach': 'hold_s1'},
    'reset_first': {'compliance_aware_approach': 'reset_first'},
    'both': {'compliance_aware_approach': 'both'},
}
TOL = 0.15


def typestore():
    store = get_typestore(Stores.ROS2_HUMBLE)
    add = {}
    for path in sorted(glob.glob('/opt/ros/humble/share/vision_msgs/msg/*.msg')):
        name = 'vision_msgs/msg/' + os.path.basename(path)[:-4]
        with open(path, encoding='utf-8') as f:
            add.update(get_types_from_msg(f.read(), name))
    store.register(add)
    return store


STORE = None


def fsm_parameters(run_dir):
    params = dict(yaml.safe_load(open(SIM_YAML))['compliance_fsm_node']['ros__parameters'])
    overlay = yaml.safe_load(open(os.path.join(run_dir, 'overlay.yaml')))
    params.update(overlay.get('compliance_fsm_node', {}).get('ros__parameters', {}))
    params.pop('use_sim_time', None)
    params['use_ros_clock'] = False   # the replay patches the clock itself
    return params


def camera_of(name, events_topics):
    """'confirm_cctv1' or '/compliance/cctv1/confirmed' -> index in events_topics."""
    for i, topic in enumerate(events_topics):
        cam = topic.split('/')[2]          # 'cctv1'
        if cam in name:
            return i
    return None


def read_stream(run_dir, events_topics):
    """The run's FSM inputs as a list of (kind, payload) in recorder order,
    plus the logged FSM transitions."""
    global STORE
    STORE = STORE or typestore()
    stream, logged = [], []
    frames_open = {}   # (node, stamp) -> frame entry still collecting persons
    with Reader(os.path.join(run_dir, 'bag')) as reader:
        conns = [c for c in reader.connections if c.topic in INPUTS]
        for conn, _, raw in reader.messages(connections=conns):
            msg = STORE.deserialize_cdr(raw, conn.msgtype)
            topic = conn.topic
            if topic == '/clock':
                stream.append(('clock', msg.clock.sec + msg.clock.nanosec * 1e-9))
            elif topic.endswith('/confirmed'):
                stream.append(('events', (msg, camera_of(topic, events_topics))))
            elif topic == '/compliance/event_metadata':
                stream.append(('metadata', types.SimpleNamespace(data=msg.data)))
            elif topic == '/compliance/nav_status':
                stream.append(('nav', types.SimpleNamespace(data=msg.data)))
            elif topic == '/scan':   # Python floats, as rclpy delivers them
                stream.append(('scan', types.SimpleNamespace(
                    ranges=[float(r) for r in msg.ranges], range_min=float(msg.range_min),
                    range_max=float(msg.range_max), angle_min=float(msg.angle_min),
                    angle_increment=float(msg.angle_increment))))
            elif topic == '/compliance/autonomy_paused':
                stream.append(('paused', types.SimpleNamespace(data=msg.data)))
            elif topic == '/compliance/confirmation_debug':
                d = json.loads(msg.data)
                key = (d['node'], d['stamp'])
                frame = frames_open.get(key)
                if frame is None:   # first record of a frame: deliver it here
                    frame = {'camera': camera_of(d['node'], events_topics), 'persons': []}
                    frames_open[key] = frame
                    stream.append(('frame', frame))
                frame['persons'].append(d['track_id'])
            elif topic == '/compliance/fsm_state':
                logged.append(json.loads(msg.data))
    return stream, logged


def person(track):
    """A tracked person as the frame callback reads it (no box in the logs)."""
    hyp = types.SimpleNamespace(hypothesis=types.SimpleNamespace(class_id='person'))
    bbox = types.SimpleNamespace(center=types.SimpleNamespace(
        position=types.SimpleNamespace(x=-1e6, y=-1e6)), size_x=0.0, size_y=0.0)
    return types.SimpleNamespace(id=track, results=[hyp], bbox=bbox)


def replay(stream, params, variant):
    """Run the node over the stream. Returns its events, and the sim times of
    the confirmed frames and of all rebuilt frames per camera."""
    overrides = {**params, **variant}
    if variant and any(k in variant for k in ('sustained_confirmation_ratio',
                                              'compliance_aware_approach')):
        overrides['frame_topics'] = FRAME_TOPICS[:len(params['events_topics'])]
    node = ComplianceFsmNode(parameter_overrides=[Parameter(k, value=v)
                                                  for k, v in overrides.items()])
    clock = {'t': 0.0}
    node.now_s = lambda: clock['t']
    node.state_since = 0.0
    events = []
    publish = node.publish_fsm_state

    def record(previous, new, reason, track, room, **extra):
        events.append({'stamp': clock['t'], 'previous_state': previous, 'new_state': new,
                       'reason': reason, 'stage_reached': node.stage_reached, **extra})
        publish(previous, new, reason, track, room, **extra)
    node.publish_fsm_state = record
    conf_times = collections.defaultdict(list)
    frame_times = collections.defaultdict(list)
    try:
        for kind, payload in stream:
            if kind == 'clock':
                if payload > clock['t']:
                    clock['t'] = payload
                    node.tick()
            elif kind == 'events':
                msg, camera = payload
                node.events_callback(msg, camera)
                if msg.detections:
                    conf_times[camera].append(clock['t'])
            elif kind == 'frame':
                frame_times[payload['camera']].append(clock['t'])
                if node.variants_active:
                    node.frame_callback(types.SimpleNamespace(
                        detections=[person(t) for t in payload['persons']]), payload['camera'])
            elif kind == 'metadata':
                node.metadata_callback(payload)
            elif kind == 'nav':
                node.nav_status_callback(payload)
            elif kind == 'scan':
                node.scan_callback(payload)
            elif kind == 'paused':
                node.paused_callback(payload)
    finally:
        node.destroy_node()
    return events, conf_times, frame_times


def transitions(events, until=math.inf):
    return [(e['stamp'], e['new_state'], e['reason']) for e in events
            if e['reason'] != 'cooldown_end' and e['previous_state'] != e['new_state']
            and e['stamp'] <= until]


def same_transitions(replayed, logged):
    if [(s, r) for _, s, r in replayed] != [(s, r) for _, s, r in logged]:
        return False, math.inf
    worst = max([abs(a[0] - b[0]) for a, b in zip(replayed, logged)] or [0.0])
    return worst <= TOL, worst


def first_s1(events):
    return next((e['stamp'] for e in events if e['new_state'] in ('PA_WARNING', 'APPROACH')
                 and e['previous_state'] == 'MONITORING'), math.nan)


def first_outcome(events):
    e = next((e for e in events if e.get('outcome')), None)
    return (e['outcome'], e.get('stage_reached'), e['stamp']) if e else ('none', '', math.nan)


def offline_s1(conf_times, frame_times, delay, clear):
    """offline_extensions' sustained rule on exactly the replayed inputs."""
    best = math.nan
    for camera, times in conf_times.items():
        frames = np.array(sorted(frame_times.get(camera, [])))

        def count(t0, t1, frames=frames):
            return float(((frames > t0) & (frames <= t1)).sum())
        assert (delay, clear) == (ox.CONFIRM_DELAY, ox.CLEAR), 'timings differ from the offline rule'
        t = ox.escalation_times(sorted(times), count, -math.inf, math.inf, True,
                                data_end=frames[-1] if len(frames) else -math.inf)
        if np.isfinite(t) and not (t >= best):
            best = t
    return best


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', default=os.path.join(ROOT, 'evaluation', 'data', 'manifest.csv'))
    ap.add_argument('--tag', default='baseline')
    ap.add_argument('--runs', help='comma-separated run ids (default: every ok run of the tag)')
    ap.add_argument('--sustained-events', default=os.path.join(
        ROOT, 'evaluation', 'results', 'offline_extensions', 'sustained_events.csv'))
    ap.add_argument('--outdir', default=os.path.join(ROOT, 'evaluation', 'results', 'fsm_replay'))
    cli = ap.parse_args()

    table = pd.read_csv(cli.manifest, dtype=str, keep_default_na=False)
    table = table.drop_duplicates('run_id', keep='last')
    table = table[(table.tag == cli.tag) & (table.status == 'ok')]
    if cli.runs:
        table = table[table.run_id.isin(cli.runs.split(','))]

    rclpy.init()
    rows = []
    try:
        for run in table.to_dict('records'):
            run_dir = os.path.join(ROOT, run['run_dir'])
            params = fsm_parameters(run_dir)
            stream, logged = read_stream(run_dir, params['events_topics'])
            end = max((p for k, p in stream if k == 'clock'), default=math.nan)
            row = {'run_id': run['run_id'], 'scenario': run['scenario'],
                   'ground_truth': run['ground_truth'],
                   'logged_s1': first_s1(logged),
                   'logged_outcome': first_outcome(logged)[0],
                   'logged_stage': first_outcome(logged)[1]}
            for name, variant in VARIANTS.items():
                events, conf_times, frame_times = replay(stream, params, variant)
                outcome, stage, t_out = first_outcome(events)
                row[f'{name}_s1'] = first_s1(events)
                row[f'{name}_outcome'] = outcome
                row[f'{name}_stage'] = stage
                row[f'{name}_t_outcome'] = t_out
                row[f'{name}_holds'] = sum(e['reason'] == 'compliance_hold' for e in events)
                row[f'{name}_deferred'] = sum(e['reason'] == 'target_lost_deferred' for e in events)
                row[f'{name}_approached'] = any(e['new_state'] == 'APPROACH' for e in events)
                hold = next((e['stamp'] for e in events if e['reason'] == 'compliance_hold'), None)
                done = next((e['stamp'] for e in events if hold is not None and e['stamp'] >= hold
                             and e['previous_state'] == 'PA_WARNING'
                             and e['new_state'] != 'PA_WARNING'), math.nan)
                row[f'{name}_hold_s'] = done - hold if hold is not None else math.nan
                if name == 'default':
                    ok, worst = same_transitions(transitions(events, end), transitions(logged, end))
                    row['default_reproduces_log'] = ok
                    row['default_worst_dt'] = worst
                if name == 'sustained_0.6':
                    row['offline_same_inputs_s1'] = offline_s1(
                        conf_times, frame_times, params['monitor_confirm_duration'],
                        params['compliance_clear_duration'])
            rows.append(row)
            print(f"{run['run_id']:22s} default={'ok' if row['default_reproduces_log'] else 'DIFF'} "
                  f"sustained={row['sustained_0.6_s1']:.2f} offline={row['offline_same_inputs_s1']:.2f} "
                  f"hold={row['hold_s1_outcome']}/{row['hold_s1_stage']} "
                  f"reset={row['reset_first_outcome']}/{row['reset_first_stage']}",
                  file=sys.stderr)
    finally:
        rclpy.try_shutdown()

    df = pd.DataFrame(rows)
    os.makedirs(cli.outdir, exist_ok=True)
    df.to_csv(os.path.join(cli.outdir, 'replay_runs.csv'), index=False, float_format='%.3f')
    write_report(df, cli)


def agree(a, b):
    return (np.isnan(a) and np.isnan(b)) or (np.isfinite(a) and np.isfinite(b) and abs(a - b) <= TOL)


def write_report(df, cli):
    n = len(df)
    md = ['# Bag replay of the compliance FSM (real node class)\n',
          f'Generated by `evaluation/scripts/replay_fsm.py` from {n} runs of run set `{cli.tag}`.'
          ' Open-loop: the node receives the recorded inputs of each run.\n']

    ok = int(df.default_reproduces_log.sum())
    md.append('## 1. Default parameters reproduce the logged FSM\n')
    md.append(f'Same transitions, same reasons, times within {TOL} s: **{ok} / {n}** runs '
              f'(largest time difference among them: {df.loc[df.default_reproduces_log, "default_worst_dt"].max():.2f} s).\n')
    bad = df[~df.default_reproduces_log]
    if len(bad):
        md.append('Runs that differ: ' + ', '.join(bad.run_id) + '\n')

    s = df['sustained_0.6_s1']
    same = df.apply(lambda r: agree(r['sustained_0.6_s1'], r['offline_same_inputs_s1']), axis=1)
    md.append('## 2. sustained_confirmation_ratio = 0.6: online (node) vs offline rule\n')
    md.append(f'(a) Identical inputs (frames rebuilt from the debug records): escalation and S1 time '
              f'within {TOL} s agree in **{int(same.sum())} / {n}** runs.')
    if (~same).any():
        md.append('  Differ: ' + ', '.join(df.loc[~same, 'run_id']))
    md.append('')
    if os.path.isfile(cli.sustained_events):
        sus = pd.read_csv(cli.sustained_events)
        per_run = sus.groupby('run_id').agg(esc=('escalates_sustained', 'any'),
                                            t=('t_sustained', 'min'))
        merged = df.set_index('run_id').join(per_run, how='left')
        dec = merged.esc.fillna(False) == np.isfinite(merged['sustained_0.6_s1'])
        both = merged[np.isfinite(merged['sustained_0.6_s1']) & merged.esc.fillna(False)]
        dt = (both['sustained_0.6_s1'] - both.t).abs()
        md.append(f'(b) Against the published offline result (`sustained_events.csv`, all YOLO frames '
                  f'counted from the heartbeat): escalation decision agrees in **{int(dec.sum())} / {len(merged)}** '
                  f'runs; where both escalate, S1 times differ by at most {dt.max():.2f} s '
                  f'(median {dt.median():.2f} s).')
        if (~dec).any():
            md.append('  Decision differs: ' + ', '.join(merged.index[~dec]))
        md.append('')
    md.append('| Scenario | runs | escalate (default) | escalate (sustained 0.6) |\n|---|---|---|---|')
    for scen, g in df.groupby('scenario'):
        md.append(f'| {scen} | {len(g)} | {int(np.isfinite(g["default_s1"]).sum())} | '
                  f'{int(np.isfinite(g["sustained_0.6_s1"]).sum())} |')
    md.append('')

    md.append('## 3. compliance_aware_approach: open-loop outcome preview\n')
    md.append('Outcome / stage of the first escalation per run. Open loop: once a variant decides '
              'differently from the logged run, the recorded robot motion and navigation no longer '
              'follow from its decisions; the Gazebo runs (Phase C) are the result.\n')
    cols = ['logged'] + [v for v in VARIANTS if v not in ('sustained_0.6',)]
    lines = ['| Scenario | ' + ' | '.join(cols) + ' |', '|' + '---|' * (len(cols) + 1)]
    for scen, g in df.groupby('scenario'):
        cells = []
        for c in cols:
            pairs = collections.Counter(zip(g[f'{c}_outcome'], g[f'{c}_stage']))
            cells.append(', '.join(f'{o}/{st} ×{k}' if o != 'none' else f'none ×{k}'
                                   for (o, st), k in pairs.most_common()))
        lines.append(f'| {scen} | ' + ' | '.join(cells) + ' |')
    md.extend(lines)
    md.append('\nHow often each mechanism acted (runs per scenario; only scenarios where it acted), '
              'and the time from S1 to the outcome (median, s):\n')
    md.append('| Scenario | variant | S1 held | S1 hold, median / max (s) | target loss deferred | '
              'approached (S2) | S1 to outcome (s) |')
    md.append('|---|---|---|---|---|---|---|')
    for scen, g in df.groupby('scenario'):
        for v in ('default', 'hold_s1', 'reset_first', 'both'):
            held, deferred = int((g[f'{v}_holds'] > 0).sum()), int((g[f'{v}_deferred'] > 0).sum())
            if v != 'default' and not (held or deferred):
                continue
            if v == 'default' and not ((g['hold_s1_holds'] > 0).any() or (g['reset_first_deferred'] > 0).any()):
                continue
            lat = (g[f'{v}_t_outcome'] - g[f'{v}_s1']).median()
            h = g[f'{v}_hold_s'].dropna()
            hold = f'{h.median():.1f} / {h.max():.1f}' if len(h) else '–'
            md.append(f'| {scen} | {v} | {held} | {hold} | {deferred} | '
                      f'{int(g[f"{v}_approached"].sum())} | {lat:.1f} |')
    with open(os.path.join(cli.outdir, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md) + '\n')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
