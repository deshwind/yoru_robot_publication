#!/usr/bin/env python3
"""Phase 6: event-level sensitivity of the C1-C7 decision rule, offline.

Every tracked person in every frame of every baseline run is logged on
/compliance/confirmation_debug with its D, P, T, S, gate results (C1, C2, C4)
and C7 risk (Phase 2). The persistence counter (C4) depends only on C1-C3, not
on the weights or threshold, so every decision the node would have made under
another weight/threshold setting can be recomputed exactly from these logs,
with the node's own arithmetic (confirmation_rule.py):

  C = w_D*D + w_P*P + w_T*T + w_S*S
  confirmed  = C >= tau AND C1 AND C2 AND C4 AND C7 risk != high
  uncertain  = not confirmed AND C >= tau - 0.20

Events: one per (run, camera). cctv1 events carry the run's ground truth;
cctv2 events are always negative (room B never has a device). A violation
event's frames are limited to [onset, scripted cessation] (the period during
which the person was actually violating); other events use all frames. An
event is 'confirmed' if >= 1 frame is confirmed: the FSM escalates 5 s after a
single confirmed frame (docs/sim_audit.md section 4 item 10), so this is exactly
the decision that triggers an intervention. Otherwise it is 'uncertain' if any
frame was uncertain, else 'rejected'.

Validation (must hold before any result is used):
  1. baseline recomputation == every logged online decision and C, bit for bit
  2. baseline event decision (any camera confirmed) == the real FSM escalated

Configurations: named weight sets x tau {0.50, 0.60, 0.70}; one-at-a-time
weight changes of +-0.05 / +-0.10 with the other weights rescaled
proportionally (sum stays 1), at tau = 0.60.

Statistics per configuration: confirmed / uncertain / rejected events, false
confirmations, misses, decision stability vs baseline, exact McNemar test vs
baseline on correctness (Holm-corrected over configurations), precision /
recall / F1 (positive = violation event), plus a tau sweep per weight set.

Usage:
  python3 evaluation/scripts/sensitivity_offline.py [--manifest M ...] [--outdir D]
"""

import argparse
import gzip
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'src', 'yoru_core'))
from yoru_core import confirmation_rule as rule  # noqa: E402  (the node's own rule)

BASE_W = (0.40, 0.30, 0.20, 0.10)
NAMED = {'baseline': BASE_W, 'device_emphasis': (0.50, 0.25, 0.15, 0.10),
         'persistence_emphasis': (0.30, 0.25, 0.35, 0.10),
         'balanced': (0.25, 0.25, 0.25, 0.25)}
THRESHOLDS = (0.50, 0.60, 0.70)
OAT_DELTAS = (-0.10, -0.05, 0.05, 0.10)
WEIGHT_NAMES = ('w_D', 'w_P', 'w_T', 'w_S')
BAND = 0.20


def _without_support(weights):
    """Copy of confirmation_rule.without_support (Phase 7), used until that
    function is in the installed package; identical arithmetic."""
    rest = weights['w_D'] + weights['w_P'] + weights['w_T']
    total = rest + weights['w_S']
    return {'w_D': weights['w_D'] * total / rest, 'w_P': weights['w_P'] * total / rest,
            'w_T': weights['w_T'] * total / rest, 'w_S': 0.0}


without_support = getattr(rule, 'without_support', _without_support)
STORE = get_typestore(Stores.ROS2_HUMBLE)
FRAME_COLS = ['run_id', 'node', 'track_id', 't', 'D', 'P', 'T', 'S', 'C1', 'C2', 'C4',
              'fp', 'C_logged', 'decision_logged', 'w_D', 'w_P', 'w_T', 'w_S',
              'tau_logged', 'band_logged']


# ------------------------------------------------------------ configurations

def configurations():
    configs = []
    for name, w in NAMED.items():
        for tau in THRESHOLDS:
            configs.append({'config': f'{name}@{tau:.2f}', 'family': 'named',
                            'weights': w, 'tau': tau})
    for i, wname in enumerate(WEIGHT_NAMES):
        for delta in OAT_DELTAS:
            new = BASE_W[i] + delta
            if not 0.0 <= new <= 1.0:
                continue
            scale = (1.0 - new) / (1.0 - BASE_W[i])
            w = tuple(round(new if j == i else BASE_W[j] * scale, 10) for j in range(4))
            configs.append({'config': f'OAT {wname}{delta:+.2f}@0.60', 'family': 'oat',
                            'weights': w, 'tau': 0.60})
    # Phase 7 ablations at the baseline setting (same semantics as the node flags)
    base = dict(zip(WEIGHT_NAMES, BASE_W))
    for criterion in ('c4', 'c5', 'c7'):
        w = tuple(without_support(base)[n] for n in WEIGHT_NAMES) if criterion == 'c5' else BASE_W
        configs.append({'config': f'ablate {criterion.upper()}@0.60', 'family': 'ablation',
                        'weights': w, 'tau': 0.60, 'ablate': criterion})
    return configs


# -------------------------------------------------------------------- frames

def read_run(run_dir):
    frames, gt, fsm = [], [], []
    with Reader(os.path.join(run_dir, 'bag')) as reader:
        conns = [c for c in reader.connections if c.topic in (
            '/compliance/confirmation_debug', '/compliance/scenario_ground_truth',
            '/compliance/fsm_state')]
        for conn, _, raw in reader.messages(connections=conns):
            data = json.loads(STORE.deserialize_cdr(raw, conn.msgtype).data)
            {'/compliance/confirmation_debug': frames,
             '/compliance/scenario_ground_truth': gt,
             '/compliance/fsm_state': fsm}[conn.topic].append(data)
    return frames, gt, fsm


def load(manifests, cache):
    if cache and os.path.isfile(cache + '.frames.csv.gz'):
        # round_trip: pandas' default parser can be 1 ulp off, which would
        # break the bit-exact reproduction (validation 1 would catch it)
        return (pd.read_csv(cache + '.frames.csv.gz', keep_default_na=False,
                            na_values=[''], float_precision='round_trip'),
                pd.read_csv(cache + '.runs.csv', keep_default_na=False, na_values=[''],
                            float_precision='round_trip'))
    frame_rows, run_rows = [], []
    for manifest in manifests:
        table = pd.read_csv(manifest, dtype=str, keep_default_na=False)
        table = table.drop_duplicates('run_id', keep='last')  # latest row per run wins
        for run in table.to_dict('records'):
            if run['status'] != 'ok':
                continue
            run_dir = os.path.join(ROOT, run['run_dir'])
            frames, gt, fsm = read_run(run_dir)
            events = {e['event']: e['stamp'] for e in gt if e.get('event') != 'state'}
            s1 = next((e['stamp'] for e in fsm if e['new_state'] == 'PA_WARNING'), math.nan)
            t_end = max([f['recv_stamp'] for f in frames] or [math.nan])
            run_rows.append({
                'run_id': run['run_id'], 'tag': run['tag'], 'scenario': run['scenario'],
                'seed': run['seed'], 'ground_truth': run['ground_truth'],
                't_v': events.get('violation_onset', math.nan),
                't_cessation': events.get('violation_cessation', math.nan),
                't_end': t_end, 't_s1_actual': s1})
            for f in frames:
                w = f['weights']
                frame_rows.append([run['run_id'], f['node'], f['track_id'], f['recv_stamp'],
                                   f['D'], f['P'], f['T'], f['S'], f['C1'], f['C2'], f['C4'],
                                   f['C7_fp_risk'], f['C'], f['decision'], w['w_D'], w['w_P'],
                                   w['w_T'], w['w_S'], f['confirm_confidence'],
                                   f['uncertain_confidence']])
            print(f"read {run['run_id']}: {len(frames)} frames", file=sys.stderr)
    frames = pd.DataFrame(frame_rows, columns=FRAME_COLS)
    runs = pd.DataFrame(run_rows)
    if cache:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with gzip.open(cache + '.frames.csv.gz', 'wt') as f:
            frames.to_csv(f, index=False, float_format='%.17g')   # lossless floats
        runs.to_csv(cache + '.runs.csv', index=False, float_format='%.17g')
    return frames, runs


# ----------------------------------------------------------------- decisions

def decide(frames, weights, tau, band=BAND, ablate=None):
    """Vectorised node rule: each product and sum is a separate IEEE op, in
    the node's order, so the result is bit-identical to confirmation_rule."""
    wD, wP, wT, wS = weights
    C = (wD * frames['D'].to_numpy() + wP * frames['P'].to_numpy()) \
        + wT * frames['T'].to_numpy()
    C = C + wS * frames['S'].to_numpy()
    c4 = np.ones(len(frames), bool) if ablate == 'c4' else frames['C4'].to_numpy(bool)
    c7 = (np.ones(len(frames), bool) if ablate == 'c7'
          else frames['fp'].to_numpy() != 'high')
    gates = frames['C1'].to_numpy(bool) & frames['C2'].to_numpy(bool) & c4 & c7
    confirmed = (C >= tau) & gates
    uncertain = ~confirmed & (C >= tau - band)
    return C, confirmed, uncertain


def event_table(frames, runs, confirmed, uncertain):
    """One row per (run, camera) event with its decision and first-confirm time."""
    f = frames[['run_id', 'node', 't']].copy()
    f['confirmed'], f['uncertain'] = confirmed, uncertain
    f = f.merge(runs[['run_id', 'ground_truth', 't_v', 't_cessation']], on='run_id')
    is_violation = (f['ground_truth'] == 'violation') & (f['node'] == 'confirm_cctv1')
    end = f['t_cessation'].fillna(np.inf)
    in_window = ~is_violation | ((f['t'] >= f['t_v']) & (f['t'] <= end))
    f = f[in_window]
    f['t_conf'] = np.where(f['confirmed'], f['t'], np.inf)
    ev = f.groupby(['run_id', 'node'], sort=False).agg(
        any_conf=('confirmed', 'any'), any_unc=('uncertain', 'any'),
        n_conf=('confirmed', 'sum'), t_first_conf=('t_conf', 'min')).reset_index()
    ev = ev.merge(runs[['run_id', 'scenario', 'ground_truth', 't_v']], on='run_id')
    ev['positive'] = (ev['ground_truth'] == 'violation') & (ev['node'] == 'confirm_cctv1')
    ev['decision'] = np.where(ev['any_conf'], 'confirmed',
                              np.where(ev['any_unc'], 'uncertain', 'rejected'))
    ev['latency'] = np.where(ev['any_conf'] & ev['positive'],
                             ev['t_first_conf'] - ev['t_v'], np.nan)
    return ev


# ---------------------------------------------------------------- statistics

def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2.0 * tail)


def holm(pvalues):
    order = np.argsort(pvalues)
    m, adjusted, running = len(pvalues), np.empty(len(pvalues)), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def prf(ev):
    tp = int((ev['any_conf'] & ev['positive']).sum())
    fp = int((ev['any_conf'] & ~ev['positive']).sum())
    fn = int((~ev['any_conf'] & ev['positive']).sum())
    precision = tp / (tp + fp) if tp + fp else math.nan
    recall = tp / (tp + fn) if tp + fn else math.nan
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall and not math.isnan(precision + recall) else math.nan)
    return tp, fp, fn, precision, recall, f1


# -------------------------------------------------------------------- report

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', action='append')
    ap.add_argument('--outdir', default=os.path.join(ROOT, 'evaluation', 'results', 'sensitivity'))
    ap.add_argument('--cache', default=os.path.join(ROOT, 'evaluation', 'data', 'frames_baseline'))
    ap.add_argument('--no-cache', action='store_true')
    cli = ap.parse_args()
    manifests = cli.manifest or [os.path.join(ROOT, 'evaluation', 'data', 'manifest.csv')]
    os.makedirs(cli.outdir, exist_ok=True)
    frames, runs = load(manifests, None if cli.no_cache else cli.cache)
    report = [f'# Offline sensitivity analysis (Phase 6)\n\nGenerated by '
              f'`evaluation/scripts/sensitivity_offline.py` from {len(runs)} runs, '
              f'{len(frames)} logged person-frames.\n']

    # ---- validation 1: baseline recomputation == logged online decisions
    logged_w = frames[list(WEIGHT_NAMES)].drop_duplicates()
    if len(logged_w) != 1 or tuple(logged_w.iloc[0]) != BASE_W or \
            set(frames['tau_logged']) != {0.6}:
        sys.exit('frames were not logged under the baseline weights/threshold')
    C, conf, unc = decide(frames, BASE_W, 0.60)
    online = frames['decision_logged'].to_numpy()
    offline = np.where(conf, 'confirmed', np.where(unc, 'uncertain', 'rejected'))
    c_mismatch = int((C != frames['C_logged'].to_numpy()).sum())
    d_mismatch = int((offline != online).sum())
    # cross-check with the node's own scalar function on a sample
    sample = frames.sample(n=min(2000, len(frames)), random_state=1)
    scalar_mismatch = sum(
        rule.composite_confidence(r.D, r.P, r.T, r.S, dict(zip(WEIGHT_NAMES, BASE_W))) != r.C_logged
        for r in sample.itertuples())
    report.append('## Validation\n')
    report.append(f'1. Baseline recomputation vs logged online values: C mismatches '
                  f'**{c_mismatch}** / {len(frames)}, decision mismatches **{d_mismatch}** / '
                  f'{len(frames)} (scalar `confirmation_rule` cross-check on '
                  f'{len(sample)} frames: {scalar_mismatch} mismatches).')
    base_ev = event_table(frames, runs, conf, unc)
    # validation 2: event-level decision vs the real FSM
    escalated_offline = base_ev.groupby('run_id')['any_conf'].any()
    escalated_actual = runs.set_index('run_id')['t_s1_actual'].notna()
    agree = (escalated_offline.reindex(escalated_actual.index).fillna(False)
             == escalated_actual)
    first_conf = base_ev[base_ev.any_conf].groupby('run_id')['t_first_conf'].min()
    first_conf_all = frames[conf].groupby('run_id')['t'].min()
    delay = (runs.set_index('run_id')['t_s1_actual'] - first_conf_all).dropna()
    report.append(f'2. Event decision "any camera confirmed" vs the real FSM escalating: '
                  f'**{int(agree.sum())} / {len(agree)}** runs agree'
                  + (f'; S1 followed the first confirmed frame by {delay.min():.2f}-'
                     f'{delay.max():.2f} s (median {delay.median():.2f} s; the FSM rule is 5 s).'
                     if len(delay) else '.'))
    disagree = agree[~agree].index.tolist()
    if disagree:
        report.append(f'   Disagreeing runs: {disagree}')
    if c_mismatch or d_mismatch:
        report.append('\n**Validation failed - results below must not be used.**')

    # ---- all configurations
    configs = configurations()
    rows, per_event = [], {}
    base_correct = np.where(base_ev['positive'], base_ev['any_conf'], ~base_ev['any_conf'])
    base_frame = np.where(conf, 2, np.where(unc, 1, 0))   # frame-level 3-way decision
    for cfg in configs:
        _, c_cfg, u_cfg = decide(frames, cfg['weights'], cfg['tau'], ablate=cfg.get('ablate'))
        frame_dec = np.where(c_cfg, 2, np.where(u_cfg, 1, 0))
        ev = event_table(frames, runs, c_cfg, u_cfg)
        ev = ev.set_index(['run_id', 'node']).reindex(
            base_ev.set_index(['run_id', 'node']).index).reset_index()
        per_event[cfg['config']] = ev['decision'].to_numpy()
        correct = np.where(ev['positive'], ev['any_conf'], ~ev['any_conf'])
        b = int((base_correct & ~correct).sum())   # baseline right, config wrong
        c = int((~base_correct & correct).sum())   # baseline wrong, config right
        tp, fp, fn, precision, recall, f1 = prf(ev)
        changed = int((ev['any_conf'].to_numpy() != base_ev['any_conf'].to_numpy()).sum())
        rows.append({
            'config': cfg['config'], 'family': cfg['family'],
            **dict(zip(WEIGHT_NAMES, cfg['weights'])), 'tau': cfg['tau'],
            'events': len(ev), 'confirmed': int((ev.decision == 'confirmed').sum()),
            'uncertain': int((ev.decision == 'uncertain').sum()),
            'rejected': int((ev.decision == 'rejected').sum()),
            'false_confirmations': fp, 'misses': fn, 'tp': tp,
            'precision': precision, 'recall': recall, 'f1': f1,
            'decisions_changed': changed,
            'stability_binary': 1.0 - changed / len(ev),
            'stability_3level': float((ev['decision'].to_numpy()
                                       == base_ev['decision'].to_numpy()).mean()),
            'mcnemar_b': b, 'mcnemar_c': c, 'p_exact': mcnemar_exact(b, c),
            'median_latency_s': float(np.nanmedian(ev['latency'])) if ev['latency'].notna().any()
            else math.nan,
            'frames_confirmed': int(c_cfg.sum()),
            # frame level: how many individual person-frame decisions differ
            'frames_changed': int((frame_dec != base_frame).sum()),
            'frame_stability': float((frame_dec == base_frame).mean())})
    res = pd.DataFrame(rows)
    nonbase = res['config'] != 'baseline@0.60'
    res.loc[nonbase, 'p_holm'] = holm(res.loc[nonbase, 'p_exact'].to_numpy())
    res.to_csv(os.path.join(cli.outdir, 'configurations.csv'), index=False, float_format='%.4f')
    events_out = base_ev[['run_id', 'node', 'scenario', 'ground_truth', 'positive']].copy()
    for name, dec in per_event.items():
        events_out[name] = dec
    events_out.to_csv(os.path.join(cli.outdir, 'event_decisions.csv'), index=False)

    # ---- threshold sweep per named weight set
    sweep = []
    for name, w in NAMED.items():
        for tau in np.round(np.arange(0.40, 0.9001, 0.01), 2):
            _, c_cfg, u_cfg = decide(frames, w, tau)
            tp, fp, fn, precision, recall, f1 = prf(event_table(frames, runs, c_cfg, u_cfg))
            sweep.append({'weights': name, 'tau': tau, 'tp': tp, 'fp': fp, 'fn': fn,
                          'precision': precision, 'recall': recall, 'f1': f1})
    pd.DataFrame(sweep).to_csv(os.path.join(cli.outdir, 'threshold_sweep.csv'), index=False,
                               float_format='%.4f')
    # ... and a compact view of it

    # ---- markdown
    sweep = pd.DataFrame(sweep)
    n_pos = int(base_ev['positive'].sum())
    report.append(f'\n## Events\n\n{len(base_ev)} events: {n_pos} violation (cctv1 of a violation '
                  f'run), {int((~base_ev.positive & (base_ev.node == "confirm_cctv1")).sum())} '
                  f'negative cctv1, {int((base_ev.node == "confirm_cctv2").sum())} negative cctv2 '
                  '(room B, never a device).\n')
    report.append('## Configurations\n')
    report.append('Event-level columns, then frame level (every logged person-frame).\n')
    report.append('| Configuration | w_D | w_P | w_T | w_S | τ | confirmed | uncertain | rejected | '
                  'false conf. | misses | precision | recall | F1 | changed vs baseline | '
                  'stability | McNemar b/c | p (exact) | p (Holm) | median latency (s) | '
                  'confirmed frames | frames changed | frame stability |')
    report.append('|' + '---|' * 23)
    for r in res.itertuples():
        report.append(
            f'| {r.config} | {r.w_D:.3f} | {r.w_P:.3f} | {r.w_T:.3f} | {r.w_S:.3f} | {r.tau:.2f} | '
            f'{r.confirmed} | {r.uncertain} | {r.rejected} | {r.false_confirmations} | {r.misses} | '
            f'{r.precision:.3f} | {r.recall:.3f} | {r.f1:.3f} | {r.decisions_changed} | '
            f'{r.stability_binary:.3f} | {r.mcnemar_b}/{r.mcnemar_c} | {r.p_exact:.3g} | '
            + ('–' if pd.isna(r.p_holm) else f'{r.p_holm:.3g}')
            + f' | {r.median_latency_s:.2f} | {r.frames_confirmed} | {r.frames_changed} | '
            f'{r.frame_stability:.4f} |')
    report.append('\n## Precision / recall / F1 versus threshold (event level)\n')
    report.append('Full sweep τ = 0.40 … 0.90 (step 0.01) in `threshold_sweep.csv`.\n')
    report.append('| Weight set | τ range with precision = recall = 1 | F1 @ 0.50 | F1 @ 0.60 | '
                  'F1 @ 0.70 | lowest τ with a miss | highest τ with a false confirmation |')
    report.append('|---|---|---|---|---|---|---|')
    for name in NAMED:
        g = sweep[sweep['weights'] == name]
        perfect = g[(g.fn == 0) & (g.fp == 0)]['tau']
        miss = g[g.fn > 0]['tau']
        false = g[g.fp > 0]['tau']
        f1_at = {t: g[np.isclose(g.tau, t)]['f1'].iloc[0] for t in THRESHOLDS}
        report.append(f'| {name} | '
                      + (f'{perfect.min():.2f}–{perfect.max():.2f}' if len(perfect) else 'none')
                      + ' | ' + ' | '.join(f'{f1_at[t]:.3f}' for t in THRESHOLDS)
                      + f" | {f'{miss.min():.2f}' if len(miss) else '> 0.90'}"
                      + f" | {f'{false.max():.2f}' if len(false) else '< 0.40'} |")
    changing = res[nonbase & (res['decisions_changed'] > 0)]
    report.append('\n## Configurations that change at least one event decision '
                  '(candidates for Gazebo re-runs)\n')
    if len(changing):
        for r in changing.itertuples():
            ev_changed = events_out[events_out[r.config].eq('confirmed')
                                    != events_out['baseline@0.60'].eq('confirmed')]
            report.append(f'- **{r.config}**: {r.decisions_changed} event(s): '
                          + ', '.join(f'{e.run_id} ({e.node}, {e.ground_truth}: '
                                      f'{e["baseline@0.60"]} → {e[r.config]})'
                                      for _, e in ev_changed.head(12).iterrows())
                          + (' …' if len(ev_changed) > 12 else ''))
    else:
        report.append('None: every configuration gives the same confirmed / not-confirmed '
                      'decision for every event as the baseline.')
    with open(os.path.join(cli.outdir, 'sensitivity.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(report) + '\n')
    print('\n'.join(report[:4]))
    print(f'-> {cli.outdir}')


if __name__ == '__main__':
    main()
