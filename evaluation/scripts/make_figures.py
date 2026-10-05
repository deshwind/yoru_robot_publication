#!/usr/bin/env python3
"""Paper figures (static PDF + PNG) from the Phase 5-6 results.

  fig1_outcomes      outcome distribution per scenario (100 % stacked bars)
  fig2_timeline      median escalation timeline per scenario (stage durations)
  fig3_metrics       timing and proximity distributions (small multiples)
  fig4_threshold     event-level precision / recall / F1 vs threshold per weight set

Colours are the dataviz skill's reference palette, used unchanged (validated
there; ordering is part of its CVD safety): categorical slots in fixed order,
one-hue ramp for ordered stages, muted gray for "no escalation", text in ink
tokens, recessive hairline grid.

Usage: python3 evaluation/scripts/make_figures.py [--metrics M] [--sensitivity DIR] [--out DIR]
"""

import argparse
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Reference palette (light mode)
SURFACE, INK, INK2, MUTED = '#fcfcfb', '#0b0b0b', '#52514e', '#898781'
GRID, AXIS = '#e1e0d9', '#c3c2b7'
SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7',
          '#e34948']
RAMP = ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#104281']  # ordinal steps 250..650

OUTCOMES = [  # fixed slot per outcome, identical in every figure
    ('complied', 'complied', SERIES[0]),
    ('target_lost', 'target lost', SERIES[1]),
    ('logged', 'logged (S4)', SERIES[2]),
    ('safety_stop', 'SAFE_STOP', SERIES[3]),
    ('admin_override', 'admin override', SERIES[4]),
    ('none', 'no escalation', AXIS),
]


def style():
    plt.rcParams.update({
        'font.family': 'sans-serif', 'font.size': 8, 'axes.titlesize': 8.5,
        'axes.labelsize': 8, 'xtick.labelsize': 7.5, 'ytick.labelsize': 7.5,
        'legend.fontsize': 7.5, 'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
        'savefig.facecolor': SURFACE, 'axes.edgecolor': AXIS, 'axes.linewidth': 0.6,
        'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': INK2,
        'text.color': INK, 'axes.titlecolor': INK, 'axes.grid': False,
        'xtick.major.width': 0.5, 'ytick.major.width': 0, 'legend.frameon': False,
        'axes.spines.top': False, 'axes.spines.right': False, 'pdf.fonttype': 42})


def hgrid(ax, axis='x'):
    ax.grid(True, axis=axis, color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)


def save(fig, out, name):
    for ext in ('pdf', 'png'):
        fig.savefig(os.path.join(out, f'{name}.{ext}'), dpi=300, bbox_inches='tight')
    plt.close(fig)


def scenario_order(metrics):
    order = list(dict.fromkeys(metrics['scenario']))
    viol = [s for s in order if (metrics[metrics.scenario == s].ground_truth == 'violation').all()]
    return viol + [s for s in order if s not in viol]


# ------------------------------------------------------------------ fig 1

def group_rows(metrics, order):
    """Row positions with a one-row gap + heading between the violation and
    violation-free groups."""
    gt = metrics.groupby('scenario').ground_truth.first()
    rows, headings, y = {}, [], 0
    for label, members in (('violation scenarios', [s for s in order if gt[s] == 'violation']),
                           ('violation-free scenarios',
                            [s for s in order if gt[s] != 'violation'])):
        if not members:
            continue
        headings.append((y, label))
        y += 1
        for s in members:
            rows[s] = y
            y += 1
    return rows, headings, y


def fig_outcomes(metrics, out):
    order = scenario_order(metrics)
    rows, headings, n_rows = group_rows(metrics, order)
    fig, ax = plt.subplots(figsize=(6.3, 0.24 * n_rows + 1.0))
    for scenario in order:
        row = rows[scenario]
        g = metrics[metrics.scenario == scenario]
        left = 0.0
        for key, _, colour in OUTCOMES:
            share = (g.outcome == key).mean()
            if share > 0:
                ax.barh(row, share, left=left, height=0.62, color=colour,
                        edgecolor=SURFACE, linewidth=1.2)
                left += share
        match = g.expected_outcome_match.astype(str).eq('True')
        ax.text(1.015, row, f'{int(match.sum())}/{len(g)}', va='center', ha='left',
                fontsize=7, color=INK2)
    for y, label in headings:
        ax.text(0.0, y + 0.15, label, ha='left', va='center', fontsize=7.5, color=INK2,
                fontweight='bold')
    ax.set_yticks([rows[s] for s in order], order)
    ax.set_ylim(n_rows - 0.4, -0.6)
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel('share of runs')
    ax.text(1.015, headings[0][0] + 0.15, 'matches\nexpected', ha='left', va='center',
            fontsize=6.5, color=MUTED)
    hgrid(ax)
    handles = [matplotlib.patches.Patch(color=c, label=l) for _, l, c in OUTCOMES]
    ax.legend(handles=handles, ncol=6, loc='lower left', bbox_to_anchor=(0, 1.0),
              handlelength=1, columnspacing=1.0)
    save(fig, out, 'fig1_outcomes')


# ------------------------------------------------------------------ fig 2

def fig_timeline(metrics, out):
    m = metrics[metrics.escalation_depth >= 1].copy()
    s3 = m['t_goal_reached_fsm']
    m['detect'] = m.t_conf - m.t_v
    m['S0'] = m.t_w1 - m.t_conf
    m['S1'] = m.t_s2 - m.t_w1
    m['S2'] = np.where(s3.notna(), s3 - m.t_s2, m.t_r - m.t_s2)
    m['S3+'] = np.where(s3.notna(), m.t_r - s3, np.nan)
    stages = [('detect', 'onset → confirmed'), ('S0', 'S0 delay (5 s)'), ('S1', 'S1 PA'),
              ('S2', 'S2 approach'), ('S3+', 'S3 warnings → reset / S4')]
    order = [s for s in scenario_order(metrics) if s in set(m.scenario)]
    fig, ax = plt.subplots(figsize=(6.3, 0.26 * len(order) + 1.1))
    for row, scenario in enumerate(order):
        g = m[m.scenario == scenario]
        left = 0.0
        for (col, _), colour in zip(stages, RAMP):
            dur = g[col].median()
            if np.isfinite(dur) and dur > 0:
                ax.barh(row, dur, left=left, height=0.62, color=colour,
                        edgecolor=SURFACE, linewidth=1.2)
                left += dur
        tc = (g.t_c - g.t_v).median()
        if np.isfinite(tc):
            ax.plot(tc, row, marker='o', ms=4.5, color=INK, mec=SURFACE, mew=1.2,
                    linestyle='none')
        outcome = g.outcome.mode().iat[0]
        ax.text(left + 1.0, row, dict((k, l) for k, l, _ in OUTCOMES)[outcome],
                va='center', fontsize=7, color=INK2)
    ax.set_yticks(range(len(order)), order)
    ax.invert_yaxis()
    ax.set_xlabel('time after violation onset (s, median over runs)')
    hgrid(ax)
    handles = [matplotlib.patches.Patch(color=c, label=l) for (_, l), c in zip(stages, RAMP)]
    handles.append(matplotlib.lines.Line2D([], [], marker='o', color=INK, mec=SURFACE,
                                           linestyle='none', ms=4.5,
                                           label='violation ends: stops / leaves view (t_c)'))
    ax.legend(handles=handles, ncol=3, loc='lower left', bbox_to_anchor=(0, 1.0),
              handlelength=1)
    ax.set_xlim(0, ax.get_xlim()[1] * 1.12)
    save(fig, out, 'fig2_timeline')


# ------------------------------------------------------------------ fig 3

PANELS = [('confirmation_latency', 'Confirmation latency (s)'),
          ('navigation_time', 'Navigation time (s)'),
          ('compliance_latency', 'Compliance latency (s)'),
          ('termination_latency', 'Termination latency (s)'),
          ('min_distance', 'Min robot–violator distance (m)'),
          ('min_scan_range', 'Min lidar range, S2–S3 (m)')]


def fig_metrics(metrics, out):
    order = scenario_order(metrics)
    rng = np.random.default_rng(3)
    fig, axes = plt.subplots(2, 3, figsize=(6.6, 4.6))
    for ax, (col, title) in zip(axes.flat, PANELS):
        present = [s for s in order if metrics[metrics.scenario == s][col].notna().any()]
        for row, scenario in enumerate(present):
            v = metrics[metrics.scenario == scenario][col].dropna().to_numpy()
            jitter = rng.uniform(-0.18, 0.18, len(v))
            ax.plot(v, row + jitter, 'o', ms=3.2, color=SERIES[0], alpha=0.75,
                    mec=SURFACE, mew=0.6, linestyle='none')
            ax.plot([np.median(v)] * 2, [row - 0.32, row + 0.32], color=INK, linewidth=1.4,
                    solid_capstyle='round')
        ax.set_yticks(range(len(present)), present)
        ax.set_ylim(len(present) - 0.5, -0.5)
        ax.set_title(title, loc='left')
        hgrid(ax)
        if col == 'termination_latency':
            for ref in (8, 10):
                ax.axvline(ref, color=AXIS, linewidth=0.8)
        if col == 'min_scan_range':
            ax.axvline(0.35, color=AXIS, linewidth=0.8)
    fig.text(0.01, -0.01, 'Dots: runs (jittered vertically). Bar: median. '
             'Reference lines: reset windows (8, 10 s) and SAFE_STOP distance.',
             fontsize=7, color=MUTED)
    fig.tight_layout()
    save(fig, out, 'fig3_metrics')


# ------------------------------------------------------------------ fig 4

def fig_threshold(sweep, out):
    sets = list(dict.fromkeys(sweep['weights']))
    labels = {'baseline': 'baseline 0.40/0.30/0.20/0.10',
              'device_emphasis': 'device 0.50/0.25/0.15/0.10',
              'persistence_emphasis': 'persistence 0.30/0.25/0.35/0.10',
              'balanced': 'balanced 0.25 each'}
    fig, axes = plt.subplots(1, 3, figsize=(6.6, 2.4), sharey=True)
    for ax, (col, title) in zip(axes, [('precision', 'Precision'), ('recall', 'Recall'),
                                       ('f1', 'F1')]):
        for i, name in enumerate(sets):
            g = sweep[sweep.weights == name]
            # widest first: where series coincide they stay visible as nested bands
            ax.step(g.tau, g[col], where='post', color=SERIES[i],
                    linewidth=4.2 - 1.0 * i, label=labels.get(name, name),
                    solid_joinstyle='round', zorder=2 + i)
        ax.axvline(0.60, color=AXIS, linewidth=0.8)
        ax.set_title(title, loc='left')
        ax.set_xlabel('threshold τ')
        ax.set_ylim(-0.02, 1.04)
        hgrid(ax, 'y')
    axes[0].text(0.605, 0.03, 'τ = 0.60', fontsize=6.5, color=MUTED)
    fig.legend(*axes[0].get_legend_handles_labels(), loc='lower center',
               bbox_to_anchor=(0.5, 1.0), ncol=2, handlelength=1.6, columnspacing=1.6)
    fig.text(0.5, -0.04, 'Coinciding settings are drawn as nested bands (widest first).',
             ha='center', fontsize=7, color=MUTED)
    fig.tight_layout()
    save(fig, out, 'fig4_threshold')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--metrics', default=os.path.join(ROOT, 'evaluation', 'data', 'metrics.csv'))
    ap.add_argument('--sensitivity',
                    default=os.path.join(ROOT, 'evaluation', 'results', 'sensitivity'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'evaluation', 'results', 'figures'))
    ap.add_argument('--tag', default='baseline')
    cli = ap.parse_args()
    os.makedirs(cli.out, exist_ok=True)
    style()
    metrics = pd.read_csv(cli.metrics)
    metrics = metrics[(metrics.status == 'ok') & (metrics.tag == cli.tag)]
    fig_outcomes(metrics, cli.out)
    fig_timeline(metrics, cli.out)
    fig_metrics(metrics, cli.out)
    sweep = os.path.join(cli.sensitivity, 'threshold_sweep.csv')
    if os.path.isfile(sweep):
        fig_threshold(pd.read_csv(sweep), cli.out)
    print(f'figures -> {cli.out}')


if __name__ == '__main__':
    main()
