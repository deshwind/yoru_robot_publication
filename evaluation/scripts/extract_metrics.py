#!/usr/bin/env python3
"""Phase 5: one row of metrics per run, read from the rosbag2 bags with `rosbags`.

Times (all in simulation seconds):
  t_v     scripted violation onset            /compliance/scenario_ground_truth 'violation_onset'
  t_conf  first confirmation                  first 'confirmed' /compliance/confirmation_debug (recv_stamp)
  t_w1    first warning = S1 entry            /compliance/fsm_state MONITORING -> PA_WARNING
  t_s2    S2 entry                            /compliance/fsm_state -> APPROACH
  t_g     Nav2 goal sent (accepted)           /navigate_to_pose/_action/status goal_info.stamp
  t_a     goal succeeded                      first SUCCEEDED status of that goal (bag time -> sim)
  t_c     first frame of the absence interval that completes the reset window: the first
          frame of the violator's camera after its last confirmed frame before t_r
          (if the person has left the view and no frame exists: last confirmed frame +
          median frame interval; t_c_source says which)
  t_r     FSM reset                           /compliance/fsm_state -> MONITORING with an outcome
Positions p_R / p_H: Gazebo ground truth from /gazebo/model_states (bag time -> sim).

Metrics follow the research brief; a metric that does not apply to a run is left empty
(NaN), never estimated. Messages without a header stamp are placed in sim time through the
recorded /clock (accuracy about +-0.1 s, the /clock publish period).

Usage (repo root):
  python3 evaluation/scripts/extract_metrics.py [--manifest evaluation/data/manifest.csv]
                                                [--out evaluation/data/metrics.csv]
"""

import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd
import yaml
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_types_from_msg, get_typestore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STAGE = {'S0': 0, 'S1': 1, 'S2': 2, 'S3': 3, 'S4': 4}
OUTCOMES = {'complied': 'complied', 'target_lost': 'target_lost',
            'logged_no_compliance': 'logged', 'admin_override': 'admin_override',
            'safety_stop': 'safety_stop'}
SUCCEEDED = 4
PEOPLE = ('person_1', 'person_2', 'person_3', 'intruder_1')
NAN = float('nan')

TOPICS = ['/clock', '/compliance/fsm_state', '/compliance/audio_event',
          '/compliance/scenario_ground_truth', '/compliance/actor_events',
          '/compliance/confirmation_debug', '/compliance/nav_status',
          '/navigate_to_pose/_action/status', '/navigate_to_pose/_action/feedback',
          '/plan', '/gazebo/model_states', '/scan']


def typestore():
    """Humble store + the three non-core types the bags contain."""
    store = get_typestore(Stores.ROS2_HUMBLE)
    share = '/opt/ros/humble/share'
    add = {}
    with open(os.path.join(share, 'gazebo_msgs/msg/ModelStates.msg'), encoding='utf-8') as f:
        add.update(get_types_from_msg(f.read(), 'gazebo_msgs/msg/ModelStates'))
    with open(os.path.join(share, 'nav2_msgs/action/NavigateToPose.action'),
              encoding='utf-8') as f:
        feedback = f.read().split('---')[2]
    add.update(get_types_from_msg(feedback, 'nav2_msgs/action/NavigateToPose_Feedback'))
    add.update(get_types_from_msg(
        'unique_identifier_msgs/UUID goal_id\n'
        'nav2_msgs/action/NavigateToPose_Feedback feedback\n',
        'nav2_msgs/action/NavigateToPose_FeedbackMessage'))
    store.register(add)
    return store


STORE = None


def sim(t):
    return t.sec + t.nanosec * 1e-9


class RunData:
    """Everything a run's bag holds that the metrics need."""

    def __init__(self, bag_dir):
        global STORE
        if STORE is None:
            STORE = typestore()
        self.clock = []            # (bag ns, sim s)
        self.fsm, self.audio, self.gt, self.actor, self.debug = [], [], [], [], []
        self.nav_status = []       # (bag ns, dict)
        self.goal_status = []      # (bag ns, [(goal uuid, accept sim s, status)])
        self.feedback = []         # (bag ns, recoveries)
        self.plans = []            # bag ns
        self.models = []           # (bag ns, {name: (x, y)})
        self.scan = []             # (sim s, min range > 0.2 m)
        with Reader(bag_dir) as reader:
            conns = [c for c in reader.connections if c.topic in TOPICS]
            for conn, t_bag, raw in reader.messages(connections=conns):
                msg = STORE.deserialize_cdr(raw, conn.msgtype)
                self._add(conn.topic, t_bag, msg)
        clock = np.array(self.clock) if self.clock else np.zeros((0, 2))
        self._clock_bag, self._clock_sim = clock[:, 0], clock[:, 1]

    def _add(self, topic, t_bag, msg):
        if topic == '/clock':
            self.clock.append((t_bag, sim(msg.clock)))
        elif topic == '/gazebo/model_states':
            self.models.append((t_bag, {n: (p.position.x, p.position.y)
                                        for n, p in zip(msg.name, msg.pose)
                                        if n in PEOPLE or n == 'yoru_robot'}))
        elif topic == '/scan':
            valid = [r for r in msg.ranges if msg.range_min < r < msg.range_max and r > 0.2]
            self.scan.append((sim(msg.header.stamp), min(valid) if valid else NAN))
        elif topic == '/navigate_to_pose/_action/status':
            self.goal_status.append((t_bag, [(bytes(s.goal_info.goal_id.uuid).hex(),
                                              sim(s.goal_info.stamp), s.status)
                                             for s in msg.status_list]))
        elif topic == '/navigate_to_pose/_action/feedback':
            self.feedback.append((t_bag, msg.feedback.number_of_recoveries))
        elif topic == '/plan':
            self.plans.append(t_bag)
        else:
            try:
                data = json.loads(msg.data)
            except ValueError:
                return
            target = {'/compliance/fsm_state': self.fsm, '/compliance/audio_event': self.audio,
                      '/compliance/scenario_ground_truth': self.gt,
                      '/compliance/actor_events': self.actor,
                      '/compliance/confirmation_debug': self.debug}.get(topic)
            if target is not None:
                target.append(data)
            elif topic == '/compliance/nav_status':
                self.nav_status.append((t_bag, data))

    def to_sim(self, t_bag):
        """Bag (receive) time -> sim time through the recorded /clock."""
        if len(self._clock_bag) == 0:
            return NAN
        return float(np.interp(t_bag, self._clock_bag, self._clock_sim))

    def positions(self, name, t0=-math.inf, t1=math.inf):
        out = []
        for t_bag, poses in self.models:
            if name in poses:
                t = self.to_sim(t_bag)
                if t0 <= t <= t1:
                    out.append((t, *poses[name]))
        return out

    def position_at(self, name, t):
        if not np.isfinite(t):
            return None
        track = self.positions(name)
        if not track:
            return None
        return min(track, key=lambda p: abs(p[0] - t))[1:]


def first(items, cond):
    return next((i for i in items if cond(i)), None)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1]) if a is not None and b is not None else NAN


def fsm_params(run_dir):
    """The FSM parameters actually used by the run (overlay over yoru_sim.yaml)."""
    defaults = {'compliance_clear_duration': 10.0, 'target_lost_timeout': 8.0}
    try:
        with open(os.path.join(run_dir, 'overlay.yaml'), encoding='utf-8') as f:
            overlay = yaml.safe_load(f)
        defaults.update(overlay['compliance_fsm_node']['ros__parameters'])
    except (OSError, KeyError, TypeError):
        pass
    return defaults


def metrics(run_dir, ground_truth):
    d = RunData(os.path.join(run_dir, 'bag'))
    m = {}
    gt = {e['event']: e for e in d.gt if e.get('event') != 'state'}
    layout = first(d.actor, lambda e: e.get('event') == 'layout')
    violator = layout.get('violator') if layout else None
    persons = layout.get('persons', []) if layout else []
    v_start = first(persons, lambda p: p['role'] == 'violator')
    m.update({'violator': violator, 'n_persons': len(persons),
              'violator_x0': v_start['x'] if v_start else NAN,
              'violator_y0': v_start['y'] if v_start else NAN})

    # ---------------------------------------------------------------- times
    t_v = gt['violation_onset']['stamp'] if 'violation_onset' in gt else NAN
    t_cess = gt['violation_cessation']['stamp'] if 'violation_cessation' in gt else NAN
    confirmed = [r for r in d.debug if r['decision'] == 'confirmed']
    conf = confirmed[0] if confirmed else None
    t_conf = conf['recv_stamp'] if conf else NAN

    s1 = first(d.fsm, lambda e: e['new_state'] == 'PA_WARNING')
    t_w1 = s1['stamp'] if s1 else NAN
    end = first(d.fsm, lambda e: s1 is not None and e['stamp'] >= t_w1
                and e['new_state'] == 'MONITORING' and e['reason'] in OUTCOMES)
    t_r = end['stamp'] if end else NAN
    s2 = first(d.fsm, lambda e: e['new_state'] == 'APPROACH')
    t_s2 = s2['stamp'] if s2 else NAN
    s2_exit = first(d.fsm, lambda e: s2 is not None and e['stamp'] > t_s2
                    and e['previous_state'] == 'APPROACH')
    t_s2_end = s2_exit['stamp'] if s2_exit else NAN
    s3_exit = first(d.fsm, lambda e: e['previous_state'] == 'DIRECT_WARNING')
    t_s23_end = (s3_exit['stamp'] if s3_exit else t_s2_end) if s2 else NAN

    # Nav2: first goal accepted after S2 entry, and when it succeeded
    t_g, t_a, goal_id = NAN, NAN, None
    for t_bag, statuses in d.goal_status:
        for uuid, accepted, status in statuses:
            if goal_id is None and np.isfinite(t_s2) and accepted >= t_s2 - 0.5:
                goal_id, t_g = uuid, accepted
            if uuid == goal_id and status == SUCCEEDED and not np.isfinite(t_a):
                t_a = d.to_sim(t_bag)
    goal_reached = first(d.fsm, lambda e: e['reason'] == 'goal_reached')

    m.update({'t_v': t_v, 't_conf': t_conf, 't_w1': t_w1, 't_s2': t_s2, 't_g': t_g,
              't_a': t_a, 't_r': t_r, 't_cessation_scripted': t_cess,
              't_goal_reached_fsm': goal_reached['stamp'] if goal_reached else NAN})

    # -------------------------------------------------------------- outcome
    outcome = OUTCOMES[end['reason']] if end else 'none'
    depth = max([STAGE.get(e.get('stage_reached'), 0) for e in d.fsm] or [0])
    m.update({'outcome': outcome, 'escalation_depth': depth,
              # each rate only applies to one kind of run (NaN for the other)
              'false_intervention': (depth >= 1 if ground_truth == 'no_violation' else NAN),
              'missed': (conf is None if ground_truth == 'violation' else NAN),
              'confirmed_frames': len(confirmed),
              'first_conf_D': conf['D'] if conf else NAN,
              'first_conf_C': conf['C'] if conf else NAN,
              'conf_node': conf['node'] if conf else ''})

    # ----------------------------------------------------------- latencies
    m['confirmation_latency'] = t_conf - t_v
    m['detection_to_intervention'] = t_w1 - t_conf
    m['navigation_time'] = t_a - t_g

    # absence interval (compliance reset or target loss)
    t_c, source = NAN, ''
    if end and end['reason'] in ('complied', 'target_lost'):
        room = end.get('room')
        node_records = [r for r in d.debug if r.get('room') == room] or d.debug
        node = first([r for r in node_records if r['decision'] == 'confirmed'],
                     lambda r: True)
        node = node['node'] if node else None
        frames = [r for r in d.debug if r['node'] == node]
        last_conf = [r for r in frames if r['decision'] == 'confirmed'
                     and r['recv_stamp'] < t_r]
        if last_conf:
            t_last = last_conf[-1]['recv_stamp']
            nxt = first(frames, lambda r: r['recv_stamp'] > t_last)
            stamps = sorted({r['recv_stamp'] for r in frames})
            period = float(np.median(np.diff(stamps))) if len(stamps) > 2 else NAN
            if nxt is not None and nxt['recv_stamp'] <= t_last + 2 * period:
                t_c, source = nxt['recv_stamp'], 'frame'
            else:
                t_c, source = t_last + period, 'estimated'
    params = fsm_params(run_dir)
    expected_term = {'complied': params['compliance_clear_duration'],
                     'target_lost': params['target_lost_timeout']}.get(outcome, NAN)
    term = t_r - t_c
    m.update({'t_c': t_c, 't_c_source': source,
              'compliance_latency': t_c - t_w1 if outcome == 'complied' else NAN,
              'violation_duration': t_c - t_conf if outcome == 'complied' else NAN,
              'termination_latency': term,
              'termination_expected': expected_term,
              'termination_flag': (bool(abs(term - expected_term) > 0.5)
                                   if np.isfinite(term) and np.isfinite(expected_term) else NAN),
              'cessation_detection_lag': t_c - t_cess if outcome == 'complied' else NAN})

    # ---------------------------------------------------------- navigation
    path = d.positions('yoru_robot', t_s2, t_s2_end) if np.isfinite(t_s2_end) else []
    m['path_length'] = (sum(dist(a[1:], b[1:]) for a, b in zip(path, path[1:]))
                        if len(path) > 1 else NAN)
    in_s2 = [t for t in d.plans if np.isfinite(t_s2_end)
             and t_s2 <= d.to_sim(t) <= t_s2_end]
    m['plan_updates'] = len(in_s2) if np.isfinite(t_s2_end) else NAN
    recov = [r for t, r in d.feedback if np.isfinite(t_s2_end)
             and t_s2 <= d.to_sim(t) <= t_s2_end]
    m['nav_recoveries'] = max(recov) if recov else (0 if np.isfinite(t_s2_end) else NAN)

    # ------------------------------------------------------------ distances
    p_r = d.position_at('yoru_robot', t_a)
    p_h = d.position_at(violator, t_a) if violator else None
    m['stop_back_distance'] = dist(p_r, p_h)
    robot_track = d.positions('yoru_robot', t_s2, t_s23_end) if np.isfinite(t_s23_end) else []
    min_v, min_any = NAN, NAN
    if robot_track:
        others = {n: {round(t, 2): (x, y) for t, x, y in d.positions(n, t_s2, t_s23_end)}
                  for n in PEOPLE}
        for t, x, y in robot_track:
            for name, track in others.items():
                p = track.get(round(t, 2))
                if p is None or abs(p[0]) > 6 or abs(p[1]) > 4:  # parked outside
                    continue
                dd = math.hypot(p[0] - x, p[1] - y)
                min_any = dd if not np.isfinite(min_any) else min(min_any, dd)
                if name == violator:
                    min_v = dd if not np.isfinite(min_v) else min(min_v, dd)
    m['min_distance'] = min_v
    m['min_distance_any_person'] = min_any
    warnings_before_c = [e for e in d.audio if np.isfinite(t_c) and e['stamp'] <= t_c]
    t_last_warning = warnings_before_c[-1]['stamp'] if warnings_before_c else NAN
    m['step_back_distance'] = (dist(d.position_at(violator, t_c + 3.0),
                                    d.position_at(violator, t_last_warning))
                               if outcome == 'complied' and violator else NAN)

    # ------------------------------------------------------------- warnings
    window_end = t_r if np.isfinite(t_r) else math.inf
    in_window = [e for e in d.audio if np.isfinite(t_w1) and t_w1 - 0.5 <= e['stamp'] <= window_end]
    m['warnings_delivered'] = len(in_window)
    m['pa_warnings'] = sum(e['kind'] == 'pa_warning' for e in in_window)
    m['direct_warnings'] = sum(e['kind'] == 'direct_warning' for e in in_window)

    # --------------------------------------------------------------- safety
    m['safe_stop_count'] = sum(e['new_state'] == 'SAFE_STOP' for e in d.fsm)
    scans = [r for t, r in d.scan if np.isfinite(t_s23_end) and t_s2 <= t <= t_s23_end
             and np.isfinite(r)]
    m['min_scan_range'] = min(scans) if scans else NAN
    m['target_loss_count'] = sum(e['reason'] == 'target_lost' for e in d.fsm)

    # ------------------------------------------------------ quality control
    # Effective cctv1 perception rate in SIM time: YOLO inference is CPU
    # bound, so a loaded machine lowers it - visible here, per run.
    stamps = sorted({r['recv_stamp'] for r in d.debug if r['node'] == 'confirm_cctv1'})
    m['cctv1_frame_hz'] = ((len(stamps) - 1) / (stamps[-1] - stamps[0])
                           if len(stamps) > 10 else NAN)
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', action='append',
                    help='manifest CSV(s); default evaluation/data/manifest.csv')
    ap.add_argument('--out', default=os.path.join(ROOT, 'evaluation', 'data', 'metrics.csv'))
    cli = ap.parse_args()
    manifests = cli.manifest or [os.path.join(ROOT, 'evaluation', 'data', 'manifest.csv')]
    rows = []
    for manifest in manifests:
        table = pd.read_csv(manifest, dtype=str, keep_default_na=False)
        # a redone run appends a new row: the latest row per run is authoritative
        table = table.drop_duplicates('run_id', keep='last')
        for run in table.to_dict('records'):
            row = {k: run[k] for k in ('run_id', 'tag', 'scenario', 'seed', 'status',
                                       'ground_truth', 'expected_outcome', 'w_D', 'w_P',
                                       'w_T', 'w_S', 'confirm_confidence',
                                       'uncertain_confidence', 'ablation', 'rtf',
                                       'code_sha256', 'run_dir')}
            expected = row['expected_outcome'].split()[0]
            row['expected_outcome'] = OUTCOMES.get(expected, expected)  # same names as 'outcome'
            run_dir = os.path.join(ROOT, run['run_dir'])
            if run['status'] == 'ok' and os.path.isdir(os.path.join(run_dir, 'bag')):
                try:
                    row.update(metrics(run_dir, run['ground_truth']))
                    row['expected_outcome_match'] = row['outcome'] == row['expected_outcome']
                except Exception as exc:  # noqa: BLE001 - record, never guess
                    row['extract_error'] = f'{type(exc).__name__}: {exc}'
            rows.append(row)
            print(f"{row['run_id']:28s} {row['status']:6s} {row.get('outcome', '-'):15s}",
                  file=sys.stderr)
    out = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(cli.out), exist_ok=True)
    out.to_csv(cli.out, index=False, float_format='%.4f')
    print(f'wrote {len(out)} rows -> {cli.out}', file=sys.stderr)


if __name__ == '__main__':
    main()
