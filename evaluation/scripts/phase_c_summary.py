#!/usr/bin/env python3
"""Phase C summary for the paper: statistics, tables and figures of the FSM variants.

Compares each `compliance_aware_approach` mode with the baseline's runs of the same
scenario and seed (paired design), on scenarios H, C and A:

  - outcome and escalation depth: counts, share with Wilson 95 % CI, and the exact
    McNemar test on the seed-paired changes (binomial test on discordant pairs);
  - H: distance the robot drove towards the person (path length; 0 m when no approach
    was started), with the exact sign test on the paired differences;
  - C and A: outcome-time differences from the baseline (median, largest).

Inputs: evaluation/data/metrics.csv (baseline, committed) and
evaluation/results/phase_c/aware_<mode>/metrics.csv (made by extract_metrics.py).
The path figure reads the run recordings: the baseline-configuration panel uses the
reproduction run repro_wsl/H/0 (the original baseline bags are lost).

Writes evaluation/results/phase_c/: stats.csv, summary.md, summary.tex and
figures/fig_phase_c_H_paths.{pdf,png}, figures/fig_phase_c_outcomes.{pdf,png}.

  python3 evaluation/scripts/phase_c_summary.py
"""

import math
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402
from scipy.stats import binomtest  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_metrics as em  # noqa: E402
from make_figures import AXIS, GRID, INK, INK2, MUTED, OUTCOMES, SERIES, SURFACE, save, style  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
RES = os.path.join(ROOT, 'evaluation', 'results', 'phase_c')
FIG = os.path.join(RES, 'figures')
MODES = [('hold_s1', 'aware_hold_s1'), ('reset_first', 'aware_reset_first'), ('both', 'aware_both')]
SCENARIOS = ['H', 'C', 'A']
SEEDS = range(10)
PATH_RUNS = [  # panel title, run directory, metrics file holding the run (for the distance driven)
    ('baseline config.', 'evaluation/data/repro/repro_wsl/H/0', 'evaluation/results/repro_wsl/metrics.csv'),
    ('hold_s1', 'evaluation/data/variants/aware_hold_s1/H/0', 'evaluation/results/phase_c/aware_hold_s1/metrics.csv'),
    ('reset_first', 'evaluation/data/variants/aware_reset_first/H/0', 'evaluation/results/phase_c/aware_reset_first/metrics.csv'),
    ('both', 'evaluation/data/variants/aware_both/H/0', 'evaluation/results/phase_c/aware_both/metrics.csv'),
]


def wilson(k, n, z=1.96):
    if n == 0:
        return math.nan, math.nan
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def exact_paired_p(b, c):
    """Two-sided exact test on discordant pairs (McNemar / sign test)."""
    return 1.0 if b + c == 0 else binomtest(b, b + c, 0.5).pvalue


def load():
    base = pd.read_csv(os.path.join(ROOT, 'evaluation', 'data', 'metrics.csv'))
    base = base[(base.status == 'ok') & base.scenario.isin(SCENARIOS) & base.seed.isin(SEEDS)]
    variants = {}
    for mode, tag in MODES:
        path = os.path.join(RES, tag, 'metrics.csv')
        if os.path.isfile(path):
            v = pd.read_csv(path)
            variants[mode] = v[(v.status == 'ok') & v.scenario.isin(SCENARIOS)]
    return base, variants


def driven(row):
    """Distance driven towards the person: path length, 0 m if no approach (S2) started."""
    return 0.0 if pd.isna(row.t_s2) else float(row.path_length) if not pd.isna(row.path_length) else math.nan


def statistics(base, variants):
    rows = []
    b = base.set_index(['scenario', 'seed'])
    for mode, v in variants.items():
        for s in SCENARIOS:
            vs = v[v.scenario == s]
            pairs = [(r, b.loc[(s, r.seed)]) for r in vs.itertuples() if (s, r.seed) in b.index]
            n = len(pairs)
            if n == 0:
                continue
            changed = sum(1 for r, x in pairs if (r.outcome, r.escalation_depth) != (x.outcome, x.escalation_depth))
            outcome = pd.Series([r.outcome for r, _ in pairs]).value_counts()
            top, k = outcome.index[0], int(outcome.iloc[0])
            lo, hi = wilson(k, n)
            base_outcome = pd.Series([x.outcome for _, x in pairs]).value_counts().index[0]
            row = {'mode': mode, 'scenario': s, 'pairs': n, 'baseline_outcome': base_outcome,
                   'variant_outcome': top, 'variant_outcome_n': k, 'wilson_lo': lo, 'wilson_hi': hi,
                   'depth_variant': ','.join(str(int(d)) for d in sorted({r.escalation_depth for r, _ in pairs})),
                   'changed_pairs': changed, 'p_exact_paired': exact_paired_p(changed, 0)}
            if s == 'H':
                dv = np.array([driven(r) for r, _ in pairs])
                db = np.array([driven(x) for _, x in pairs])
                diff = dv - db
                row.update(driven_variant_min=np.nanmin(dv), driven_variant_max=np.nanmax(dv),
                           driven_baseline_median=np.nanmedian(db),
                           driven_p_sign=exact_paired_p(int((diff < -0.05).sum()), int((diff > 0.05).sum())))
            else:
                dt = np.array([r.t_r - x.t_r for r, x in pairs], dtype=float)
                row.update(outcome_time_diff_median=np.nanmedian(dt), outcome_time_diff_maxabs=np.nanmax(np.abs(dt)))
            rows.append(row)
    return pd.DataFrame(rows)


def write_tables(st, variants):
    st.to_csv(os.path.join(RES, 'stats.csv'), index=False)
    both_n = len(variants.get('both', []))
    prov = '' if both_n >= 30 else f' `both` is provisional ({both_n} of 30 runs).'
    md = ['# Phase C summary: FSM design variants vs the baseline (paired by scenario and seed)', '',
          f'Generated by `evaluation/scripts/phase_c_summary.py`.{prov}', '',
          '| Mode | Scenario | Pairs | Baseline | Variant (Wilson 95 % CI) | Depth | Changed pairs | Exact paired p | Robot drove towards the person (H) / outcome-time diff (C, A) |',
          '|---|---|---|---|---|---|---|---|---|']
    for r in st.itertuples():
        rng = (f'{r.driven_variant_min:.2f} m (all runs)' if r.scenario == 'H' and r.driven_variant_min == r.driven_variant_max
               else f'{r.driven_variant_min:.2f}–{r.driven_variant_max:.2f} m') if r.scenario == 'H' else ''
        extra = (f'{rng} (baseline median {r.driven_baseline_median:.2f} m; sign test p = {r.driven_p_sign:.3g})'
                 if r.scenario == 'H' else f'median {r.outcome_time_diff_median:+.2f} s, largest {r.outcome_time_diff_maxabs:.2f} s')
        md.append(f'| {r.mode} | {r.scenario} | {r.pairs} | {r.baseline_outcome} | {r.variant_outcome} {r.variant_outcome_n}/{r.pairs} '
                  f'[{100 * r.wilson_lo:.0f}, {100 * r.wilson_hi:.0f}] % | {r.depth_variant} | {r.changed_pairs} | {r.p_exact_paired:.3g} | {extra} |')
    md += ['', 'Exact paired p: two-sided exact test on the seed-paired changes of outcome or escalation depth '
           '(McNemar; all changes are in one direction). Sign test: paired differences in distance driven '
           '(|difference| > 0.05 m).', '']
    with open(os.path.join(RES, 'summary.md'), 'w') as f:
        f.write('\n'.join(md))
    tex = ['% Generated by evaluation/scripts/phase_c_summary.py - requires \\usepackage{booktabs}',
           '\\begin{table}[t]\\centering\\small',
           '\\caption{FSM design variants against the baseline, paired by scenario and seed. Outcome share with Wilson 95\\,\\% CI; '
           'exact paired test on changed outcomes; H: distance the robot drove towards the person (0\\,m: no approach).'
           + (f' The \\texttt{{both}} set is provisional ({both_n} of 30 runs).' if both_n < 30 else '') + '}',
           '\\begin{tabular}{llrlllrl}', '\\toprule',
           'Mode & Scen. & $n$ & Baseline & Variant & Depth & Changed & $p$ \\\\', '\\midrule']
    for r in st.itertuples():
        tex.append(f'{r.mode.replace("_", chr(92) + "_")} & {r.scenario} & {r.pairs} & {r.baseline_outcome.replace("_", chr(92) + "_")} & '
                   f'{r.variant_outcome.replace("_", chr(92) + "_")} {100 * r.variant_outcome_n / r.pairs:.0f}\\,\\% [{100 * r.wilson_lo:.0f}, {100 * r.wilson_hi:.0f}] & '
                   f'S{r.depth_variant} & {r.changed_pairs} & {r.p_exact_paired:.2g} \\\\')
    tex += ['\\bottomrule', '\\end{tabular}', '\\end{table}', '']
    h = st[st.scenario == 'H']
    tex += ['\\begin{table}[t]\\centering\\small',
            '\\caption{Scenario H (the person stops during the PA warning): distance the robot drove towards the person.}',
            '\\begin{tabular}{lrcc}', '\\toprule', 'Mode & $n$ & Distance driven (m) & Sign test $p$ \\\\', '\\midrule',
            f'baseline & {int(h.pairs.max())} & {h.driven_baseline_median.iloc[0]:.2f} (median) & -- \\\\']
    for r in h.itertuples():
        dist = (f'{r.driven_variant_min:.2f} (all runs)' if r.driven_variant_min == r.driven_variant_max
                else f'{r.driven_variant_min:.2f}--{r.driven_variant_max:.2f}')
        tex.append(f'{r.mode.replace("_", chr(92) + "_")} & {r.pairs} & {dist} & {r.driven_p_sign:.2g} \\\\')
    tex += ['\\bottomrule', '\\end{tabular}', '\\end{table}', '']
    with open(os.path.join(RES, 'summary.tex'), 'w') as f:
        f.write('\n'.join(tex))


def load_map():
    with open(os.path.join(ROOT, 'maps', 'sim', 'main_map.yaml')) as f:
        meta = yaml.safe_load(f)
    img = plt.imread(os.path.join(ROOT, 'maps', 'sim', meta['image']))
    h, w = img.shape[:2]
    x0, y0 = meta['origin'][:2]
    return img, (x0, x0 + w * meta['resolution'], y0, y0 + h * meta['resolution'])


def fig_paths():
    img, extent = load_map()
    fig, axes = plt.subplots(1, len(PATH_RUNS), figsize=(7.0, 1.95))
    stage_names = {'PA_WARNING': 'S1', 'APPROACH': 'S2', 'DIRECT_WARNING': 'S3'}
    for ax, (title, rel, metrics_file) in zip(axes, PATH_RUNS):
        d = em.RunData(os.path.join(ROOT, rel, 'bag'))
        ax.imshow(img, cmap='gray', extent=extent, origin='upper', vmin=0, vmax=255, alpha=0.35)
        robot = d.positions('yoru_robot')
        violator = next((g.get('violator') for g in d.gt if g.get('violator')), 'person_1')
        person = [p for p in d.positions(violator) if -6 < p[1] < 6 and -4 < p[2] < 4]
        if person:
            ax.plot(person[-1][1], person[-1][2], 'o', color=SERIES[1], ms=5, zorder=4)
        if robot:
            ax.plot([p[1] for p in robot], [p[2] for p in robot], color=SERIES[0], lw=1.6, zorder=5)
            ax.plot(robot[0][1], robot[0][2], 's', color=SERIES[0], ms=4, zorder=6)
        events = [e for e in d.fsm if e['new_state'] != e['previous_state']]
        for e in events:
            pos = d.position_at('yoru_robot', e['stamp'])
            if pos is None:
                continue
            label = stage_names.get(e['new_state'], e['reason'].replace('_', ' '))
            ax.plot(*pos, 'D', color=SERIES[3], mec=INK, mew=0.4, ms=3.5, zorder=7)
        final = events[-1] if events else None
        outcome = f"{final['reason'].replace('_', ' ')} ({final.get('stage_reached', '')})" if final else 'none'
        # same definition as the tables (extract_metrics path_length; 0 m without an approach),
        # so the drive back to base after the outcome is not counted
        m = pd.read_csv(os.path.join(ROOT, metrics_file))
        run = m[m.run_dir.str.rstrip('/').str.endswith(rel.split('evaluation/data/')[-1].split('/', 1)[1])].iloc[-1]
        drove = driven(run)
        ax.set_title(f'{title}\n{outcome}\ndrove {drove:.2f} m', fontsize=7, linespacing=1.15)
        ax.set_xlim(-6.2, 6.2)
        ax.set_ylim(-4.2, 4.2)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
    handles = [plt.Line2D([], [], color=SERIES[0], lw=1.6, label='robot path'),
               plt.Line2D([], [], marker='s', color=SERIES[0], lw=0, ms=4, label='robot base'),
               plt.Line2D([], [], marker='o', color=SERIES[1], lw=0, ms=5, label='person (stopped in S1)'),
               plt.Line2D([], [], marker='D', color=SERIES[3], mec=INK, lw=0, ms=3.5, label='stage change')]
    fig.legend(handles=handles, loc='lower center', ncol=4, bbox_to_anchor=(0.5, -0.08))
    fig.subplots_adjust(wspace=0.04, left=0.01, right=0.99, top=0.80, bottom=0.04)
    save(fig, FIG, 'fig_phase_c_H_paths')


def fig_outcomes(base, variants, st):
    cols = [('baseline', base)] + [(m, variants[m]) for m, _ in MODES if m in variants]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 2.6), gridspec_kw={'width_ratios': [1.6, 1]})
    y, labels = 0, []
    for s in SCENARIOS:
        for name, df in cols:
            sub = df[df.scenario == s]
            n = len(sub)
            left = 0.0
            for key, _, colour in OUTCOMES:
                k = int((sub.outcome == key).sum())
                if k:
                    ax1.barh(y, k / n, left=left, height=0.7, color=colour, edgecolor=SURFACE, linewidth=0.8)
                    left += k / n
            labels.append((y, f'{s}  {name}  (n={n})'))
            y += 1
        y += 0.6
    ax1.set_yticks([p for p, _ in labels])
    ax1.set_yticklabels([l for _, l in labels], fontsize=6.5)
    ax1.invert_yaxis()
    ax1.set_xlim(0, 1)
    ax1.set_xlabel('share of runs')
    present = {o for _, df in cols for o in df.outcome.unique()}
    ax1.legend(handles=[matplotlib.patches.Patch(color=c, label=l) for k, l, c in OUTCOMES if k in present],
               loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=3)
    ax1.set_title('Outcomes per scenario and mode', loc='left')
    h_rows = [('baseline', base[base.scenario == 'H'])] + [(m, variants[m][variants[m].scenario == 'H']) for m, _ in MODES if m in variants]
    for i, (name, df) in enumerate(h_rows):
        vals = [driven(r) for r in df.itertuples()]
        ax2.scatter(vals, np.full(len(vals), i) + np.linspace(-0.15, 0.15, len(vals)), s=10,
                    color=SERIES[0] if name == 'baseline' else SERIES[2], alpha=0.8, linewidths=0)
    ax2.set_yticks(range(len(h_rows)))
    ax2.set_yticklabels([n for n, _ in h_rows])
    ax2.invert_yaxis()
    ax2.set_xlim(-0.1, 1.8)
    ax2.set_xlabel('distance driven to the person (m)')
    ax2.grid(True, axis='x', color=GRID, linewidth=0.5)
    ax2.set_axisbelow(True)
    ax2.set_title('Scenario H: robot approach', loc='left')
    both_n = len(variants.get('both', []))
    if both_n < 30:
        ax2.text(1.0, -0.36, f'both: provisional, {both_n} of 30 runs', transform=ax2.transAxes,
                 ha='right', fontsize=6.5, color=MUTED)
    fig.tight_layout()
    save(fig, FIG, 'fig_phase_c_outcomes')


def main():
    style()
    os.makedirs(FIG, exist_ok=True)
    base, variants = load()
    st = statistics(base, variants)
    write_tables(st, variants)
    fig_outcomes(base, variants, st)
    fig_paths()
    print(st[['mode', 'scenario', 'pairs', 'variant_outcome', 'variant_outcome_n', 'changed_pairs',
              'p_exact_paired']].to_string(index=False))
    print(f'-> {RES}/stats.csv, summary.md, summary.tex, figures/')


if __name__ == '__main__':
    main()
