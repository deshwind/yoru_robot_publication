#!/usr/bin/env python3
"""Offline extensions of the Phase 6 analysis (no change under src/).

1. DEPLOYMENT THRESHOLDS - every frame recomputed with the yoru_real.yaml
   values device_confidence = 0.3 and confounder_override_confidence = 0.3.

   C7 (code, event_confirmation_node.py): risk 'high' becomes 'overridden'
   when C2 and D >= override; C2 needs a device with D > device_confidence.
   With override <= device_confidence every frame that can be confirmed (C2)
   is overridden, so C7 can never block a confirmation. Checked on the logs.

   device_confidence 0.6 -> 0.3: D is logged only for a device that passed
   0.6 (otherwise 0), so a device scoring in (0.3, 0.6] is not in the logs.
   The scenario publisher's noise is seeded and its random draws depend only
   on the number of matched frames (recorded in the ground-truth heartbeat),
   so the injected scores are REPLAYED exactly (DetectionNoise from the
   source tree), validated against (a) the dropout counts at every heartbeat
   and (b) the logged D values, bit for bit and in order. Lowering
   device_confidence only adds C2 frames, raises the persistence counter and
   raises C, so it can only ADD confirmations: decisions are computed exactly
   without those frames (lower bound) and an event that is not confirmed but
   contains such frames is reported as 'could confirm' (upper bound).

2. SUSTAINED-CONFIRMATION RULE - the FSM escalates 5 s after a single
   confirmed frame (docs/sim_audit.md section 4 item 10). Alternative:
   escalate at the first FSM tick T >= t0 + 5 s (t0 = start of the
   confirmation episode; an episode ends after 10 s without confirmation, as
   in the FSM) at which >= 60 % of the camera's YOLO frames in (T - 5, T]
   contained a confirmed person. The denominator counts ALL YOLO frames,
   including those without any person (frame_stats in the ground-truth
   heartbeat), so a missed person counts against the rule. The baseline rule
   is replayed with the same code and must reproduce the real FSM.

3. OUTCOME vs TRUTH - crosstab of the FSM outcome against what the simulated
   person really did (truth_behaviour / outcome_vs_truth, also added to
   metrics.csv by extract_metrics.py).

Usage:
  python3 evaluation/scripts/offline_extensions.py [--manifest M ...] [--metrics CSV]
                                                    [--outdir evaluation/results/offline_extensions]
"""

import argparse
import gzip
import json
import math
import os
import sys

import numpy as np
import pandas as pd
import yaml
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'yoru_core'))
from yoru_core.scenario_model import DetectionNoise  # noqa: E402  (the injector's own noise)

STORE = get_typestore(Stores.ROS2_HUMBLE)
BASE_W = (0.40, 0.30, 0.20, 0.10)
TAU, BAND = 0.60, 0.20
BASELINE_DEVICE, BASELINE_OVERRIDE = 0.6, 0.75
DEPLOY_DEVICE, DEPLOY_OVERRIDE = 0.3, 0.3
CONFIRM_DELAY, CLEAR, SUSTAINED_SHARE, TICK = 5.0, 10.0, 0.60, 0.1
DEVICE_CLASSES = ('cigarette', 'vape_device')
# scenario_publisher_node.injections(): class order and base score per scenario
INJECTIONS = {
    'smoking': [('cigarette', 'device'), ('hand_mouth_gesture', 0.7), ('smoke_vapour', 0.6)],
    'vaping': [('vape_device', 'device'), ('hand_mouth_gesture', 0.7)],
    'target_loss': [('cigarette', 'device')], 'brief_device': [('cigarette', 'device')],
    'phone': [('mobile_phone', 'device')], 'false_positive': [('mobile_phone', 'device')],
    'pen': [('pen', 'device')], 'straw': [('straw', 'device')],
    'c7_conflict': [('cigarette', 'c7'), ('mobile_phone', 'device')], 'walking': [],
}


# ---------------------------------------------------------------- loading

def read_run(run_dir):
    debug, gt, fsm = [], [], []
    with Reader(os.path.join(run_dir, 'bag')) as reader:
        conns = [c for c in reader.connections if c.topic in (
            '/compliance/confirmation_debug', '/compliance/scenario_ground_truth',
            '/compliance/fsm_state')]
        for conn, _, raw in reader.messages(connections=conns):
            data = json.loads(STORE.deserialize_cdr(raw, conn.msgtype).data)
            {'/compliance/confirmation_debug': debug,
             '/compliance/scenario_ground_truth': gt,
             '/compliance/fsm_state': fsm}[conn.topic].append(data)
    return debug, gt, fsm


def publisher_params(run_dir):
    with open(os.path.join(run_dir, 'overlay.yaml'), encoding='utf-8') as f:
        p = yaml.safe_load(f)['scenario_publisher_node']['ros__parameters']
    return {'scenario_type': p.get('scenario_type', 'smoking'), 'seed': int(p.get('seed', 0)),
            'sigma': float(p.get('conf_jitter_sigma', 0.0)),
            'dropout': float(p.get('dropout_prob', 0.0)),
            'bbox_px': float(p.get('bbox_jitter_px', 0.0)),
            'device_score': float(p.get('device_score', 0.78)),
            'c7_device_score': float(p.get('c7_device_score', 0.70))}


def cache_current(manifests, cache):
    """A cache is reused only if it holds exactly the runs that are 'ok' in
    the manifests now (a cache built from a partial batch is rebuilt)."""
    wanted = set()
    for manifest in manifests:
        table = pd.read_csv(manifest, dtype=str, keep_default_na=False)
        table = table.drop_duplicates('run_id', keep='last')
        wanted |= set(table.loc[table.status == 'ok', 'run_id'])
    cached = set(pd.read_csv(cache + '.runs.csv', dtype=str)['run_id'])
    return cached == wanted


def load(manifests, cache):
    if cache and os.path.isfile(cache + '.frames.csv.gz') and cache_current(manifests, cache):
        frames = pd.read_csv(cache + '.frames.csv.gz', keep_default_na=False, na_values=[''],
                             float_precision='round_trip')
        runs = pd.read_csv(cache + '.runs.csv', keep_default_na=False, na_values=[''],
                           float_precision='round_trip')
        return frames, runs
    rows, run_rows = [], []
    for manifest in manifests:
        table = pd.read_csv(manifest, dtype=str, keep_default_na=False)
        for run in table.drop_duplicates('run_id', keep='last').to_dict('records'):
            run_dir = os.path.join(ROOT, run['run_dir'])
            if run['status'] != 'ok' or not os.path.isfile(os.path.join(run_dir, 'overlay.yaml')):
                continue
            debug, gt, fsm = read_run(run_dir)
            events = {e['event']: e['stamp'] for e in gt if e.get('event') != 'state'}
            beats = [(e['stamp'], e['frame_stats']) for e in gt
                     if e.get('event') == 'state' and 'frame_stats' in e]
            if not beats:
                continue  # not a world-mode run: no frame accounting
            s1 = next((e['stamp'] for e in fsm if e['new_state'] == 'PA_WARNING'), math.nan)
            run_rows.append({
                'run_id': run['run_id'], 'tag': run['tag'], 'scenario': run['scenario'],
                'seed': run['seed'], 'ground_truth': run['ground_truth'], 'run_dir': run['run_dir'],
                't_v': events.get('violation_onset', math.nan),
                't_cessation': events.get('violation_cessation', math.nan),
                't_removed': events.get('target_removed', math.nan),
                't_end': max([d['recv_stamp'] for d in debug] or [math.nan]),
                't_s1_actual': s1, 'heartbeats': json.dumps(beats),
                **publisher_params(run_dir)})
            for d in debug:
                rows.append([run['run_id'], d['node'], d['track_id'], d['stamp'], d['recv_stamp'],
                             d['D'], d['P'], d['T'], d['S'], d['C1'], d['C2'], d['C3'], d['C4'],
                             d['fp_risk_raw'], d['C7_fp_risk'], d['C'], d['decision'],
                             d['persistence_count'], d.get('device_class') or ''])
            print(f"read {run['run_id']}: {len(debug)} records", file=sys.stderr)
    frames = pd.DataFrame(rows, columns=[
        'run_id', 'node', 'track_id', 'stamp', 't', 'D', 'P', 'T', 'S', 'C1', 'C2', 'C3', 'C4',
        'fp_raw', 'fp_logged', 'C_logged', 'decision_logged', 'persistence', 'device_class'])
    runs = pd.DataFrame(run_rows)
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with gzip.open(cache + '.frames.csv.gz', 'wt') as f:
            frames.to_csv(f, index=False, float_format='%.17g')
        runs.to_csv(cache + '.runs.csv', index=False, float_format='%.17g')
    return frames, runs


# --------------------------------------------------------------- decisions

def decide(frames, device_conf, override):
    """Node rule from the logged values. Frames whose device did not pass
    the logged 0.6 gate keep C2 = False (their score is not logged; see the
    replay below for what device_conf < 0.6 adds)."""
    D = frames['D'].to_numpy()
    c2 = frames['C2'].to_numpy(bool) & (D > device_conf)
    C = (BASE_W[0] * D + BASE_W[1] * frames['P'].to_numpy()) + BASE_W[2] * frames['T'].to_numpy()
    C = C + BASE_W[3] * frames['S'].to_numpy()
    raw = frames['fp_raw'].to_numpy()
    fp = np.where((raw == 'high') & c2 & (D >= override), 'overridden', raw)
    confirmed = (C >= TAU) & frames['C1'].to_numpy(bool) & c2 & frames['C4'].to_numpy(bool) \
        & (fp != 'high')
    uncertain = ~confirmed & (C >= TAU - BAND)
    return C, fp, confirmed, uncertain


def replay_scores(run):
    """Injected device scores, in order, for every matched frame (None = dropped)."""
    noise = DetectionNoise(int(run['seed']), run['sigma'], run['dropout'], run['bbox_px'])
    beats = json.loads(run['heartbeats'])
    matched = beats[-1][1]['violator_matched']
    plan = INJECTIONS.get(run['scenario_type'], [])
    sequence = []
    for _ in range(matched):
        if noise.dropped():
            sequence.append(None)
            continue
        device = None
        for cls, base in plan:
            noise.box(0.0, 0.0, 1.0, 1.0)
            score = noise.score(run['device_score'] if base == 'device'
                                else run['c7_device_score'] if base == 'c7' else base)
            if cls in DEVICE_CLASSES:
                device = score
        sequence.append(('device', device) if device is not None else ('none', None))
    # validation (a): dropout count at every heartbeat
    drops = np.cumsum([s is None for s in sequence])
    dropout_ok = all(stats['dropped'] == (drops[stats['violator_matched'] - 1]
                                           if stats['violator_matched'] else 0)
                     for _, stats in beats)
    return sequence, dropout_ok


# ------------------------------------------------------- sustained rule

def frame_table(frames, node_conf):
    """One row per (run, node, camera frame): time and whether any person in
    it was confirmed."""
    f = frames[['run_id', 'node', 'stamp', 't']].copy()
    f['confirmed'] = node_conf
    return f.groupby(['run_id', 'node', 'stamp'], sort=False).agg(
        t=('t', 'min'), confirmed=('confirmed', 'any')).reset_index().sort_values('t')


def escalation_times(conf_times, frame_count, start, end, sustained):
    """FSM S0 replay for one camera stream. conf_times: sorted times of
    frames with a confirmed person; frame_count(t0, t1): YOLO frames in
    (t0, t1]. Returns the escalation time (first episode only) or NaN."""
    conf_times = [t for t in conf_times if start <= t <= end]
    if not conf_times:
        return math.nan
    episodes, current = [], [conf_times[0]]
    for t in conf_times[1:]:
        if t - current[-1] > CLEAR:
            episodes.append(current)
            current = [t]
        else:
            current.append(t)
    episodes.append(current)
    arr = np.array(conf_times)
    for ep in episodes:
        t0 = ep[0]
        if not sustained:
            return t0 + CONFIRM_DELAY
        horizon = min(ep[-1] + CLEAR, end)
        for T in np.arange(t0 + CONFIRM_DELAY, horizon + 1e-9, TICK):
            n_conf = int(((arr > T - CONFIRM_DELAY) & (arr <= T)).sum())
            n_all = frame_count(T - CONFIRM_DELAY, T)
            if n_all > 0 and n_conf >= SUSTAINED_SHARE * n_all:
                return float(T)
    return math.nan


def frame_counter(run, node_frames):
    """(t0, t1] -> number of YOLO frames. cctv1 (world mode): from the
    heartbeat frame_stats, which count every YOLO frame including those
    without a person. Other cameras: frames with at least one person."""
    beats = json.loads(run['heartbeats'])
    times = np.array([b[0] for b in beats])
    counts = np.array([b[1]['frames'] for b in beats], dtype=float)

    def cctv1(t0, t1):
        return float(np.interp(t1, times, counts) - np.interp(t0, times, counts))
    ts = np.array(sorted(node_frames))

    def persons_only(t0, t1):
        return float(((ts > t0) & (ts <= t1)).sum())
    return cctv1, persons_only


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', action='append')
    ap.add_argument('--metrics', help='metrics.csv for the outcome-vs-truth crosstab')
    ap.add_argument('--outdir', default=os.path.join(ROOT, 'evaluation', 'results',
                                                     'offline_extensions'))
    ap.add_argument('--cache', default=os.path.join(ROOT, 'evaluation', 'data',
                                                    'frames_extensions'))
    cli = ap.parse_args()
    manifests = cli.manifest or [os.path.join(ROOT, 'evaluation', 'data', 'manifest.csv')]
    os.makedirs(cli.outdir, exist_ok=True)
    frames, runs = load(manifests, cli.cache)
    runs = runs.set_index('run_id', drop=False)
    md = ['# Offline extensions: deployment thresholds, sustained-confirmation rule, '
          'outcome vs truth\n',
          f'Generated by `evaluation/scripts/offline_extensions.py` from {len(runs)} world-mode '
          f'runs ({", ".join(f"{s} ×{n}" for s, n in runs.scenario.value_counts().sort_index().items())}), '
          f'{len(frames)} logged person-frames. Manifests: '
          + ', '.join(f'`{os.path.relpath(m, ROOT)}`' for m in manifests) + '.\n']

    # ========================================================= validation
    md.append('## Validation against the logs\n')
    C, fp, conf_b, unc_b = decide(frames, BASELINE_DEVICE, BASELINE_OVERRIDE)
    online = frames['decision_logged'].to_numpy()
    offline = np.where(conf_b, 'confirmed', np.where(unc_b, 'uncertain', 'rejected'))
    v = {'C': int((C != frames['C_logged'].to_numpy()).sum()),
         'C7 risk': int((fp != frames['fp_logged'].to_numpy()).sum()),
         'decision': int((offline != online).sum())}
    md.append(f'1. Baseline values (device 0.6, override 0.75) reproduce the logged online values: '
              f'C mismatches **{v["C"]}**, C7 risk (after override) mismatches **{v["C7 risk"]}**, '
              f'decision mismatches **{v["decision"]}**, of {len(frames)} frames.')

    replay_rows = []
    for run in runs.itertuples():
        seq, dropout_ok = replay_scores(runs.loc[run.run_id])
        replayed_pass = [s[1] for s in seq if s and s[0] == 'device' and s[1] > BASELINE_DEVICE]
        logged = frames[(frames.run_id == run.run_id) & (frames.node == 'confirm_cctv1')
                        & frames.C2.astype(bool)]
        # injection order = camera frame order: sort by the frame's header
        # stamp (unique per YOLO frame). recv_stamp only has the /clock
        # resolution (0.1 s), so frames can tie on it.
        logged = logged.drop_duplicates('stamp').sort_values('stamp')['D'].tolist()
        n = min(len(replayed_pass), len(logged))
        exact = replayed_pass[:n] == logged[:n]
        # Otherwise the logged values must still be an exact, ordered
        # subsequence of the replay: an injected device the node did not
        # associate with a person (C2 false: device outside the tracked mouth
        # region) is skipped. Floats are unique, so the alignment is unambiguous.
        i = skipped = matched = 0
        for value in logged:
            j = i
            while j < len(replayed_pass) and replayed_pass[j] != value:
                j += 1
            if j == len(replayed_pass):
                break                       # not in the rest of the replay
            skipped, i, matched = skipped + (j - i), j + 1, matched + 1
        beyond = len(logged) - matched
        # valid: every logged value matched in order, except values logged
        # after the replay is exhausted (frames after the last heartbeat)
        subsequence = beyond == 0 or i == len(replayed_pass)
        flips = [s[1] for s in seq if s and s[0] == 'device'
                 and DEPLOY_DEVICE < s[1] <= BASELINE_DEVICE]
        replay_rows.append({'run_id': run.run_id, 'scenario': run.scenario,
                            'matched_frames': len(seq), 'dropped': sum(s is None for s in seq),
                            'dropout_counts_match': dropout_ok,
                            'logged_D': len(logged), 'replayed_D_above_0.6': len(replayed_pass),
                            'compared': n, 'D_sequence_exact': exact,
                            'D_ordered_subsequence': bool(subsequence),
                            'injected_not_associated': skipped if subsequence else None,
                            'logged_after_last_heartbeat': beyond if subsequence else None,
                            'devices_in_(0.3,0.6]': len(flips),
                            'their_scores': ';'.join(f'{x:.3f}' for x in flips)})
    replay = pd.DataFrame(replay_rows)
    replay.to_csv(os.path.join(cli.outdir, 'noise_replay.csv'), index=False)
    ok_drop = int(replay.dropout_counts_match.sum())
    ok_seq = int(replay.D_sequence_exact.sum())
    ok_sub = int(replay.D_ordered_subsequence.sum())
    skipped = replay.loc[replay.D_ordered_subsequence & ~replay.D_sequence_exact]
    md.append(f'2. Seeded noise replay: dropout counts match every heartbeat in **{ok_drop} / '
              f'{len(replay)}** runs. The logged D values equal the replayed scores above 0.6 bit for '
              f'bit and in order in **{ok_seq} / {len(replay)}** runs, and are an exact ordered '
              f'subsequence of them in **{ok_sub} / {len(replay)}** runs '
              f'({int(replay.compared.sum())} values compared). The '
              f'{int(skipped.injected_not_associated.sum())} replayed values missing from the logs '
              f'(in {len(skipped)} runs) have no logged counterpart; this is consistent with '
              f'injected devices the node did not associate with a person in that frame (C2 '
              f'false, independent of the thresholds), not verified frame by frame. '
              f'{int(replay.logged_after_last_heartbeat.sum())} logged values come after the final '
              f'1 Hz heartbeat and are not replayed. Note: `recv_stamp` has the /clock resolution '
              f'(0.1 s), so replay order uses the camera header stamp. Details: `noise_replay.csv`.')

    # baseline FSM replay (single confirmed frame) vs the real FSM
    ft = frame_table(frames, conf_b)
    checks = []
    for run in runs.itertuples():
        t_pred = math.nan
        for node, g in ft[ft.run_id == run.run_id].groupby('node'):
            conf_t = g[g.confirmed]['t'].tolist()
            cctv1, persons = frame_counter(runs.loc[run.run_id], g['t'].tolist())
            t = escalation_times(conf_t, cctv1 if node == 'confirm_cctv1' else persons,
                                 -math.inf, math.inf, sustained=False)
            t_pred = np.nanmin([t_pred, t]) if np.isfinite(t) else t_pred
        checks.append((run.run_id, t_pred, run.t_s1_actual))
    agree = sum((np.isnan(p) and np.isnan(a)) or (abs(p - a) <= 0.15) for _, p, a in checks)
    md.append(f'3. Baseline FSM replay ("S1 = first confirmed frame + 5 s") vs the real FSM: '
              f'**{agree} / {len(checks)}** runs agree (same escalation, S1 within 0.15 s).\n')

    # ============================================= 1. deployment thresholds
    _, fp_d, conf_d, unc_d = decide(frames, DEPLOY_DEVICE, DEPLOY_OVERRIDE)
    c7_block_base = int(((frames.fp_logged == 'high') & frames.C2.astype(bool)).sum())
    c7_block_dep = int(((fp_d == 'high') & frames.C2.astype(bool).to_numpy()).sum())
    high_raw = frames.fp_raw == 'high'
    md.append('## 1. Deployment thresholds (device_confidence = override = 0.3, yoru_real.yaml)\n')
    md.append('**Can C7 ever block a confirmation?** No. Confirmation requires C2, which requires a '
              'device with D > device_confidence = 0.3; any such device has D ≥ override = 0.3, so '
              'a "high" risk is always overridden. In the logs: '
              f'{int(high_raw.sum())} frames had a confounder at the mouth; {c7_block_base} of them '
              f'had C2 and were still blocked by C7 at the baseline values; under the deployment '
              f'values **{c7_block_dep}** remain blocked.\n')
    ev = event_rows(frames, runs, ft_baseline=ft, conf_dep=conf_d, unc_dep=unc_d,
                    replay=replay.set_index('run_id'))
    ev.to_csv(os.path.join(cli.outdir, 'deployment_events.csv'), index=False)
    by = ev[ev.node == 'confirm_cctv1'].groupby('scenario', sort=False).agg(
        ground_truth=('ground_truth', 'first'), events=('run_id', 'size'),
        confirmed_baseline=('confirmed_baseline', 'sum'),
        confirmed_deployment=('confirmed_deployment', 'sum'),
        could_confirm_more=('could_confirm', 'sum'),
        devices_03_06=('devices_03_06', 'sum')).reset_index()
    by['false_conf_baseline'] = np.where(by.ground_truth == 'no_violation', by.confirmed_baseline, 0)
    by['false_conf_deployment'] = np.where(by.ground_truth == 'no_violation',
                                           by.confirmed_deployment, 0)
    by['misses_baseline'] = np.where(by.ground_truth == 'violation',
                                     by.events - by.confirmed_baseline, 0)
    by['misses_deployment'] = np.where(by.ground_truth == 'violation',
                                       by.events - by.confirmed_deployment, 0)
    by.to_csv(os.path.join(cli.outdir, 'deployment_by_scenario.csv'), index=False)
    md.append('Event decisions per scenario (cctv1; cctv2 is never a violation and had no '
              'confirmation under either setting'
              + ('' if not ev[(ev.node != 'confirm_cctv1') & (ev.confirmed_deployment
                                                             | ev.confirmed_baseline)].shape[0]
                 else ' — **except as listed in deployment_events.csv**') + '):\n')
    md.append('| Scenario | GT | events | confirmed: baseline → deployment | false conf. | misses | '
              'injected devices scoring 0.3–0.6 (not in logs, replayed) | could additionally confirm |')
    md.append('|---|---|---|---|---|---|---|---|')
    for r in by.itertuples():
        md.append(f'| {r.scenario} | {"V" if r.ground_truth == "violation" else "N"} | {r.events} | '
                  f'{r.confirmed_baseline} → {r.confirmed_deployment} | '
                  f'{r.false_conf_baseline} → {r.false_conf_deployment} | '
                  f'{r.misses_baseline} → {r.misses_deployment} | {r.devices_03_06} | '
                  f'{r.could_confirm_more} |')
    focus = by[by.scenario.isin(['B', 'B-C7', 'F-pen', 'F-straw'])]
    md.append('\nFocus scenarios: ' + '; '.join(
        f'**{r.scenario}** {r.confirmed_baseline}/{r.events} → {r.confirmed_deployment}/{r.events} '
        f'confirmed' for r in focus.itertuples()) if len(focus) else
        '\nFocus scenarios B, B-C7, F-pen, F-straw: not in the analysed runs yet.')

    # ============================================= 2. sustained rule
    md.append('\n## 2. Sustained-confirmation rule (≥ 60 % of YOLO frames confirmed in the 5 s window)\n')
    sus = sustained_rows(ft, runs)
    sus.to_csv(os.path.join(cli.outdir, 'sustained_events.csv'), index=False)
    changed = sus[sus.escalates_baseline != sus.escalates_sustained]
    md.append(f'Events whose escalation decision changes: **{len(changed)}** of {len(sus)}.\n')
    if len(changed):
        md.append('| Event | GT | baseline | sustained | confirmed frames / YOLO frames in the first window |')
        md.append('|---|---|---|---|---|')
        for r in changed.itertuples():
            md.append(f'| {r.run_id} ({r.node}) | {r.ground_truth} | '
                      f'{"escalates" if r.escalates_baseline else "no"} | '
                      f'{"escalates" if r.escalates_sustained else "no"} | {r.first_window} |')
    tv = sus[(sus.positive) & sus.escalates_baseline]
    lat = tv.assign(delay=tv.t_sustained - tv.t_baseline)
    by_s = lat.groupby('scenario', sort=False).agg(
        events=('run_id', 'size'), still_escalate=('escalates_sustained', 'sum'),
        median_extra_delay=('delay', 'median'), max_extra_delay=('delay', 'max'),
        median_d2i_baseline=('d2i_baseline', 'median'),
        median_d2i_sustained=('d2i_sustained', 'median')).reset_index()
    by_s.to_csv(os.path.join(cli.outdir, 'sustained_latency_by_scenario.csv'), index=False)
    md.append('\nDetection-to-intervention for true violations (first confirmed frame → S1):\n')
    md.append('| Scenario | violation events escalated at baseline | still escalate | median d2i baseline (s) | '
              'median d2i sustained (s) | median / max extra delay (s) |')
    md.append('|---|---|---|---|---|---|')
    for r in by_s.itertuples():
        md.append(f'| {r.scenario} | {r.events} | {r.still_escalate} | {r.median_d2i_baseline:.2f} | '
                  f'{r.median_d2i_sustained:.2f} | {r.median_extra_delay:.2f} / '
                  f'{r.max_extra_delay:.2f} |')

    # ============================================= 3. outcome vs truth
    md.append('\n## 3. FSM outcome vs what the person really did\n')
    if cli.metrics and os.path.isfile(cli.metrics):
        m = pd.read_csv(cli.metrics)
        m = m[(m.status == 'ok') & m.truth_behaviour.notna()]
        tab = pd.crosstab([m.scenario, m.truth_behaviour], m.outcome)
        tab.to_csv(os.path.join(cli.outdir, 'outcome_vs_truth.csv'))
        md.append('Rows: scenario and the person\'s real behaviour (`truth_behaviour`); columns: FSM '
                  f'outcome. From `{os.path.relpath(cli.metrics, ROOT)}`.\n')
        md.append('| Scenario | truth | ' + ' | '.join(tab.columns) + ' |')
        md.append('|' + '---|' * (2 + len(tab.columns)))
        for (s, t), r in tab.iterrows():
            md.append(f'| {s} | {t} | ' + ' | '.join(str(int(x)) for x in r) + ' |')
        interp = m.groupby('outcome_vs_truth').size().sort_values(ascending=False)
        md.append('\n`outcome_vs_truth` over all runs: ' + ', '.join(
            f'{k} {v}' for k, v in interp.items()))
    else:
        md.append('No metrics file given (`--metrics`).')

    with open(os.path.join(cli.outdir, 'report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md) + '\n')
    print('\n'.join(md))


def event_rows(frames, runs, ft_baseline, conf_dep, unc_dep, replay):
    """Event decisions (any confirmed frame in the event window) under the
    baseline and deployment values, with the replay-based upper bound."""
    f = frames[['run_id', 'node', 't']].copy()
    f['conf_b'] = frames['decision_logged'].to_numpy() == 'confirmed'
    f['conf_d'] = conf_dep
    f = f.merge(runs[['run_id', 'scenario', 'ground_truth', 't_v', 't_cessation']].reset_index(drop=True),
                on='run_id')
    viol = (f.ground_truth == 'violation') & (f.node == 'confirm_cctv1')
    end = f.t_cessation.fillna(np.inf)
    f = f[~viol | ((f.t >= f.t_v) & (f.t <= end))]
    ev = f.groupby(['run_id', 'node'], sort=False).agg(
        scenario=('scenario', 'first'), ground_truth=('ground_truth', 'first'),
        confirmed_baseline=('conf_b', 'any'), confirmed_deployment=('conf_d', 'any')).reset_index()
    ev['positive'] = (ev.ground_truth == 'violation') & (ev.node == 'confirm_cctv1')
    ev['devices_03_06'] = [int(replay.loc[r, 'devices_in_(0.3,0.6]']) if n == 'confirm_cctv1'
                           and r in replay.index else 0 for r, n in zip(ev.run_id, ev.node)]
    ev['could_confirm'] = (~ev.confirmed_deployment) & (ev.devices_03_06 > 0)
    return ev


def sustained_rows(ft, runs):
    rows = []
    for (run_id, node), g in ft.groupby(['run_id', 'node'], sort=False):
        run = runs.loc[run_id]
        positive = run.ground_truth == 'violation' and node == 'confirm_cctv1'
        start = run.t_v if positive else -math.inf
        end = run.t_cessation if positive and np.isfinite(run.t_cessation) else math.inf
        conf_t = g[g.confirmed]['t'].tolist()
        cctv1, persons = frame_counter(run, g['t'].tolist())
        counter = cctv1 if node == 'confirm_cctv1' else persons
        t_b = escalation_times(conf_t, counter, start, end, sustained=False)
        t_s = escalation_times(conf_t, counter, start, end, sustained=True)
        first = [t for t in conf_t if start <= t <= end]
        t0 = first[0] if first else math.nan
        n_conf = sum(t0 < t <= t0 + CONFIRM_DELAY for t in first) + (1 if first else 0)
        window = (f'{n_conf}/{counter(t0 - 1e-9, t0 + CONFIRM_DELAY):.0f}'
                  if first else '–')
        rows.append({'run_id': run_id, 'node': node, 'scenario': run.scenario,
                     'ground_truth': run.ground_truth, 'positive': positive,
                     'escalates_baseline': bool(np.isfinite(t_b)),
                     'escalates_sustained': bool(np.isfinite(t_s)),
                     't_first_conf': t0, 't_baseline': t_b, 't_sustained': t_s,
                     'd2i_baseline': t_b - t0, 'd2i_sustained': t_s - t0,
                     'first_window': window})
    return pd.DataFrame(rows)


if __name__ == '__main__':
    main()
