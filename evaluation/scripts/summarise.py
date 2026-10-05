#!/usr/bin/env python3
"""Phase 5: per-scenario statistics from metrics.csv.

Continuous metrics: n, mean, SD, median, IQR (Q1, Q3) and a bootstrap 95 % CI of
the mean (percentile method, 10 000 resamples, fixed seed). Rates (outcomes,
escalation, false intervention, miss, expected-outcome match, termination flag,
SAFE_STOP): k / n with a Wilson 95 % score interval. Only runs with status 'ok'
enter the statistics; failed runs are counted separately.

Outputs (in --outdir):
  continuous.csv, rates.csv, outcomes.csv     machine-readable
  tables.md                                   all tables, Markdown
  tables.tex                                  main tables, LaTeX (booktabs)

Usage: python3 evaluation/scripts/summarise.py [--metrics evaluation/data/metrics.csv]
                                              [--outdir evaluation/results]
"""

import argparse
import math
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
Z = 1.959963984540054          # two-sided 95 %
BOOTSTRAP = 10000
SEED = 20261005

CONTINUOUS = [  # (column, label, unit)
    ('confirmation_latency', 'Confirmation latency', 's'),
    ('detection_to_intervention', 'Detection to intervention', 's'),
    ('navigation_time', 'Navigation time', 's'),
    ('path_length', 'Path length (S2)', 'm'),
    ('plan_updates', 'Plan updates (S2)', ''),
    ('nav_recoveries', 'Nav2 recoveries (S2)', ''),
    ('compliance_latency', 'Compliance latency', 's'),
    ('violation_duration', 'Violation duration', 's'),
    ('termination_latency', 'Termination latency', 's'),
    ('stop_back_distance', 'Stop-back distance', 'm'),
    ('min_distance', 'Min robot-violator distance', 'm'),
    ('min_distance_any_person', 'Min robot-person distance', 'm'),
    ('step_back_distance', 'Step-back distance', 'm'),
    ('min_scan_range', 'Min lidar range (S2-S3)', 'm'),
    ('escalation_depth', 'Escalation depth', ''),
    ('warnings_delivered', 'Warnings delivered', ''),
    ('cctv1_frame_hz', 'cctv1 frame rate (sim)', 'Hz'),
    ('rtf', 'Real-time factor', ''),
]
OUTCOME_ORDER = ['complied', 'target_lost', 'logged', 'safety_stop', 'admin_override', 'none']
TIMING_TABLE = ['confirmation_latency', 'detection_to_intervention', 'navigation_time',
                'compliance_latency', 'termination_latency']
SPACE_TABLE = ['path_length', 'stop_back_distance', 'min_distance', 'step_back_distance',
               'min_scan_range']


def wilson(k, n):
    if n == 0:
        return (math.nan, math.nan, math.nan)
    p = k / n
    denom = 1 + Z ** 2 / n
    centre = (p + Z ** 2 / (2 * n)) / denom
    half = Z * math.sqrt(p * (1 - p) / n + Z ** 2 / (4 * n ** 2)) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(values, rng):
    if len(values) < 2:
        return (math.nan, math.nan)
    samples = rng.choice(values, size=(BOOTSTRAP, len(values)), replace=True).mean(axis=1)
    return tuple(np.percentile(samples, [2.5, 97.5]))


def describe(values, rng):
    v = np.asarray([x for x in values if np.isfinite(x)], dtype=float)
    if len(v) == 0:
        return {'n': 0}
    lo, hi = bootstrap_ci(v, rng)
    return {'n': len(v), 'mean': v.mean(), 'sd': v.std(ddof=1) if len(v) > 1 else math.nan,
            'median': np.median(v), 'q1': np.percentile(v, 25), 'q3': np.percentile(v, 75),
            'min': v.min(), 'max': v.max(), 'ci_low': lo, 'ci_high': hi}


def to_bool(series):
    return series.map(lambda x: {'True': True, 'False': False, True: True,
                                 False: False}.get(x, np.nan))


def fmt(x, digits=2):
    return '–' if x is None or not np.isfinite(x) else f'{x:.{digits}f}'


def mean_sd(stat):
    if stat.get('n', 0) == 0:
        return '–'
    return f"{fmt(stat['mean'])} ± {fmt(stat['sd'])}"


def rate_cell(k, n):
    p, lo, hi = wilson(k, n)
    return '–' if n == 0 else f'{k}/{n} ({100 * p:.0f} % [{100 * lo:.0f}, {100 * hi:.0f}])'


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--metrics', default=os.path.join(ROOT, 'evaluation', 'data', 'metrics.csv'))
    ap.add_argument('--outdir', default=os.path.join(ROOT, 'evaluation', 'results'))
    cli = ap.parse_args()
    os.makedirs(cli.outdir, exist_ok=True)
    rng = np.random.default_rng(SEED)

    data = pd.read_csv(cli.metrics, keep_default_na=True)
    for col in ('false_intervention', 'missed', 'expected_outcome_match', 'termination_flag'):
        if col in data:
            data[col] = to_bool(data[col].astype(object))
    ok = data[data['status'] == 'ok'].copy()
    ok['escalated'] = ok['escalation_depth'] >= 1
    ok['safe_stop'] = ok['safe_stop_count'] > 0
    order = list(dict.fromkeys(data['scenario']))

    continuous, rates, outcomes = [], [], []
    for (tag, scenario), g in ok.groupby(['tag', 'scenario'], sort=False):
        failed = int(((data['tag'] == tag) & (data['scenario'] == scenario)
                      & (data['status'] != 'ok')).sum())
        for col, label, unit in CONTINUOUS:
            if col in g:
                stat = describe(pd.to_numeric(g[col], errors='coerce'), rng)
                continuous.append({'tag': tag, 'scenario': scenario, 'metric': col,
                                   'label': label, 'unit': unit, **stat})
        for name in ('escalated', 'false_intervention', 'missed', 'expected_outcome_match',
                     'termination_flag', 'safe_stop'):
            values = g[name].dropna() if name in g else pd.Series(dtype=bool)
            k, n = int(values.sum()), int(len(values))
            p, lo, hi = wilson(k, n)
            rates.append({'tag': tag, 'scenario': scenario, 'rate': name, 'k': k, 'n': n,
                          'p': p, 'wilson_low': lo, 'wilson_high': hi})
        counts = g['outcome'].value_counts()
        outcomes.append({'tag': tag, 'scenario': scenario,
                         'ground_truth': g['ground_truth'].iloc[0],
                         'expected': g['expected_outcome'].iloc[0], 'n_ok': len(g),
                         'n_failed': failed,
                         **{o: int(counts.get(o, 0)) for o in OUTCOME_ORDER}})
    # pooled rates over all scenarios of one ground truth (per tag)
    for tag, g in ok.groupby('tag', sort=False):
        for gt_value, name in (('no_violation', 'false_intervention'), ('violation', 'missed')):
            values = g[g['ground_truth'] == gt_value][name].dropna()
            k, n = int(values.sum()), int(len(values))
            p, lo, hi = wilson(k, n)
            rates.append({'tag': tag, 'scenario': f'ALL {gt_value}', 'rate': name, 'k': k,
                          'n': n, 'p': p, 'wilson_low': lo, 'wilson_high': hi})

    cont, rate, outc = pd.DataFrame(continuous), pd.DataFrame(rates), pd.DataFrame(outcomes)
    cont.to_csv(os.path.join(cli.outdir, 'continuous.csv'), index=False, float_format='%.4f')
    rate.to_csv(os.path.join(cli.outdir, 'rates.csv'), index=False, float_format='%.4f')
    outc.to_csv(os.path.join(cli.outdir, 'outcomes.csv'), index=False)

    write_markdown(cli.outdir, cont, rate, outc, order, len(data), len(ok))
    write_latex(cli.outdir, cont, rate, outc, order)
    print(f'{len(ok)}/{len(data)} runs ok -> {cli.outdir}')


def stat_of(cont, tag, scenario, metric):
    row = cont[(cont.tag == tag) & (cont.scenario == scenario) & (cont.metric == metric)]
    return row.iloc[0].to_dict() if len(row) else {'n': 0}


def rate_of(rate, tag, scenario, name):
    row = rate[(rate.tag == tag) & (rate.scenario == scenario) & (rate.rate == name)]
    return (int(row.k.iloc[0]), int(row.n.iloc[0])) if len(row) else (0, 0)


def write_markdown(outdir, cont, rate, outc, order, n_all, n_ok):
    labels = {c: (l, u) for c, l, u in CONTINUOUS}
    lines = [f'# Simulation results\n\nGenerated by `evaluation/scripts/summarise.py` from '
             f'`metrics.csv` ({n_ok} of {n_all} runs with status ok). Continuous values: '
             'mean ± SD; full statistics (median [IQR], bootstrap 95 % CI of the mean) in '
             'the per-metric tables below and in `continuous.csv`. Rates: k/n (%) with '
             'Wilson 95 % CI. "–" = not applicable / no data.\n']
    for tag in outc.tag.unique():
        o = outc[outc.tag == tag].set_index('scenario').reindex(
            [s for s in order if s in set(outc[outc.tag == tag].scenario)])
        lines.append(f'\n## Run set `{tag}`\n\n### Outcomes\n')
        lines.append('| Scenario | Ground truth | Expected | n ok (failed) | '
                     + ' | '.join(OUTCOME_ORDER) + ' | Matches expected |')
        lines.append('|' + '---|' * (5 + len(OUTCOME_ORDER)))
        for s, r in o.iterrows():
            k, n = rate_of(rate, tag, s, 'expected_outcome_match')
            lines.append(f"| {s} | {r.ground_truth} | {r.expected} | {r.n_ok} ({r.n_failed}) | "
                         + ' | '.join(str(r[x]) for x in OUTCOME_ORDER)
                         + f' | {rate_cell(k, n)} |')
        lines.append('\n### Rates\n')
        names = ['escalated', 'false_intervention', 'missed', 'termination_flag', 'safe_stop']
        lines.append('| Scenario | ' + ' | '.join(names) + ' |')
        lines.append('|' + '---|' * (1 + len(names)))
        for s in list(o.index) + ['ALL no_violation', 'ALL violation']:
            cells = []
            for name in names:
                k, n = rate_of(rate, tag, s, name)
                cells.append(rate_cell(k, n))
            lines.append(f'| {s} | ' + ' | '.join(cells) + ' |')
        for title, cols in (('Timing (s), mean ± SD', TIMING_TABLE),
                            ('Navigation and proximity (m), mean ± SD', SPACE_TABLE)):
            lines.append(f'\n### {title}\n')
            lines.append('| Scenario | ' + ' | '.join(labels[c][0] for c in cols) + ' |')
            lines.append('|' + '---|' * (1 + len(cols)))
            for s in o.index:
                lines.append(f'| {s} | ' + ' | '.join(
                    mean_sd(stat_of(cont, tag, s, c)) for c in cols) + ' |')
        lines.append('\n### All metrics: n, mean ± SD, median [IQR], bootstrap 95 % CI of the mean\n')
        for col, label, unit in CONTINUOUS:
            lines.append(f'\n**{label}**' + (f' ({unit})' if unit else '') + '\n')
            lines.append('| Scenario | n | mean ± SD | median [IQR] | 95 % CI | min–max |')
            lines.append('|---|---|---|---|---|---|')
            for s in o.index:
                st = stat_of(cont, tag, s, col)
                if st.get('n', 0) == 0:
                    lines.append(f'| {s} | 0 | – | – | – | – |')
                    continue
                lines.append(f"| {s} | {int(st['n'])} | {mean_sd(st)} | "
                             f"{fmt(st['median'])} [{fmt(st['q1'])}, {fmt(st['q3'])}] | "
                             f"[{fmt(st['ci_low'])}, {fmt(st['ci_high'])}] | "
                             f"{fmt(st['min'])}–{fmt(st['max'])} |")
    with open(os.path.join(outdir, 'tables.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def tex(s):
    return str(s).replace('_', r'\_').replace('%', r'\%')


def write_latex(outdir, cont, rate, outc, order):
    labels = {c: (l, u) for c, l, u in CONTINUOUS}
    out = ['% Generated by evaluation/scripts/summarise.py - requires \\usepackage{booktabs}']
    for tag in outc.tag.unique():
        scen = [s for s in order if s in set(outc[outc.tag == tag].scenario)]
        o = outc[outc.tag == tag].set_index('scenario')
        out += [f'\n% ---- run set {tex(tag)}: outcomes',
                r'\begin{table}[t]\centering\small',
                rf'\caption{{Escalation outcomes per scenario (run set {tex(tag)}). '
                r'Match: runs ending in the outcome predicted from the FSM logic, '
                r'with Wilson 95\,\% CI.}',
                r'\begin{tabular}{ll' + 'r' * (1 + len(OUTCOME_ORDER)) + 'l}', r'\toprule',
                'Scenario & GT & $n$ & ' + ' & '.join(tex(x) for x in OUTCOME_ORDER)
                + r' & Match \\', r'\midrule']
        for s in scen:
            r = o.loc[s]
            k, n = rate_of(rate, tag, s, 'expected_outcome_match')
            p, lo, hi = wilson(k, n)
            gt = 'V' if r.ground_truth == 'violation' else 'N'
            out.append(f'{tex(s)} & {gt} & {r.n_ok} & '
                       + ' & '.join(str(r[x]) for x in OUTCOME_ORDER)
                       + rf' & {100 * p:.0f}\,\% [{100 * lo:.0f}, {100 * hi:.0f}] \\')
        out += [r'\bottomrule', r'\end{tabular}', r'\end{table}']
        for title, cols in (('Timing metrics (s), mean $\\pm$ SD', TIMING_TABLE),
                            ('Navigation and proximity metrics (m), mean $\\pm$ SD',
                             SPACE_TABLE)):
            out += [r'\begin{table}[t]\centering\small',
                    rf'\caption{{{title} (run set {tex(tag)}).}}',
                    r'\begin{tabular}{l' + 'c' * len(cols) + '}', r'\toprule',
                    'Scenario & ' + ' & '.join(tex(labels[c][0]) for c in cols) + r' \\',
                    r'\midrule']
            for s in scen:
                cells = []
                for c in cols:
                    st = stat_of(cont, tag, s, c)
                    cells.append('--' if st.get('n', 0) == 0
                                 else f"{fmt(st['mean'])} $\\pm$ {fmt(st['sd'])}")
                out.append(f'{tex(s)} & ' + ' & '.join(cells) + r' \\')
            out += [r'\bottomrule', r'\end{tabular}', r'\end{table}']
    with open(os.path.join(outdir, 'tables.tex'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
