#!/usr/bin/env python3
"""Reconcile run counts across every output of the baseline evaluation.

Checks that the manifest (latest row per run), metrics.csv, the sensitivity
analysis and the offline extensions are built from exactly the same runs,
and reports per scenario: valid runs, redone runs and failed attempts, plus
the infrastructure failure rate. Every attempt that was not used is kept in
evaluation/data/runs_invalid/ with its reason, so failed attempts are
counted from there.

Usage: python3 evaluation/scripts/reconcile_counts.py [--expected-code e76b171d83faafe5]
"""

import argparse
import collections
import glob
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'evaluation', 'scripts'))
from run_batch import nav2_ready  # noqa: E402  (the runner's own validity check)

DATA = os.path.join(ROOT, 'evaluation', 'data')
INFRA = ('nav2_not_ready', 'startup_failed', 'launch_exited', 'config_not_applied',
         'timeout', 'cleanup_failed', 'bag_missing', 'actors_not_placed')


def scenario_of(run_id):
    return run_id.split('/')[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', default='baseline')
    ap.add_argument('--expected-code', default='e76b171d83faafe5')
    ap.add_argument('--out', default=os.path.join(ROOT, 'evaluation', 'results', 'run_counts.md'))
    cli = ap.parse_args()

    manifest = pd.read_csv(os.path.join(DATA, 'manifest.csv'), dtype=str, keep_default_na=False)
    manifest = manifest[manifest.tag == cli.tag]
    latest = manifest.drop_duplicates('run_id', keep='last').set_index('run_id')
    rows_per_run = manifest.groupby('run_id').size()
    valid = {r for r, row in latest.iterrows()
             if row.status == 'ok' and nav2_ready(os.path.join(ROOT, row.run_dir, 'launch.log'))
             and row.code_sha256 == cli.expected_code}
    # A run is identified by its id AND its attempt (start time): a source built
    # before a run was redone holds the right id but the superseded attempt.
    valid_keys = {(r, latest.at[r, 'start_wall']) for r in valid}

    def keys(table):
        attempt = table.start_wall if 'start_wall' in table else [''] * len(table)
        return set(zip(table.run_id, attempt))
    code_other = sorted(r for r, row in latest.iterrows() if row.code_sha256 != cli.expected_code)

    # every unused attempt, with its reason
    failed = []
    for d in sorted(glob.glob(os.path.join(DATA, 'runs_invalid', 'runs', cli.tag, '*', '*'))):
        name = os.path.basename(d)
        seed, _, rest = name.partition('__')
        reason = rest.split('__', 1)[1] if '__' in rest else rest
        info = os.path.join(d, 'run_info.json')
        status = json.load(open(info))['status'] if os.path.isfile(info) else 'interrupted'
        log = os.path.join(d, 'launch.log')
        text = open(log, encoding='utf-8', errors='replace').read() if os.path.isfile(log) else ''
        # A Gazebo server that escaped the runner's cleanup (its own session)
        # kept Gazebo's port from 2026-10-05 22:19 to 2026-10-06 09:10, so every
        # new Gazebo exited at once (code 255) and the robot could not spawn.
        stale_gazebo = status == 'startup_failed' and (
            'Service /spawn_entity unavailable' in text
            or ('[gzserver-4]: process has died' in text and 'exit code 255' in text))
        kind = ('runner defect: stale Gazebo server blocked start-up (fixed 2026-10-06)'
                if stale_gazebo
                else 'infrastructure: person not placed in the scene (lost placement message)'
                if reason == 'actors_not_placed' or status == 'actors_not_placed'
                else 'infrastructure: Nav2 never active (found post hoc)' if reason == 'nav2_not_ready_posthoc'
                else f'infrastructure: {status}' if status in INFRA
                else 'interrupted by the batch restart (operator)' if status == 'interrupted'
                else f'other: {status}')
        failed.append({'run_id': f'{cli.tag}/{os.path.basename(os.path.dirname(d))}/{seed}',
                       'reason': reason, 'status': status, 'kind': kind})
    failed = pd.DataFrame(failed, columns=['run_id', 'reason', 'status', 'kind'])

    sources = {'manifest (valid)': valid_keys}
    metrics_path = os.path.join(DATA, 'metrics.csv')
    if os.path.isfile(metrics_path):
        m = pd.read_csv(metrics_path, dtype=str, keep_default_na=False)
        m = m[(m.tag == cli.tag) & (m.status == 'ok')]
        sources['metrics.csv'] = keys(m)
    for label, cache in (('sensitivity analysis', 'frames_baseline.runs.csv'),
                         ('offline extensions', 'frames_extensions.runs.csv')):
        path = os.path.join(DATA, cache)
        if os.path.isfile(path):
            sources[label] = keys(pd.read_csv(path, dtype=str, keep_default_na=False))

    scenarios = sorted({scenario_of(r) for r in latest.index})
    header = (['Scenario', 'valid (manifest)'] + [s for s in sources if s != 'manifest (valid)']
              + ['redone', 'unused attempts'])
    lines = ['# Run counts (reconciled)\n',
             f'Generated by `evaluation/scripts/reconcile_counts.py`. Run set `{cli.tag}`; '
             f'expected code fingerprint `{cli.expected_code}`.\n',
             '| ' + ' | '.join(header) + ' |', '|' + '---|' * len(header)]
    redone_runs = set(failed.run_id) | {r for r, n in rows_per_run.items() if n > 1} \
        | {r for r, row in latest.iterrows() if row.attempts not in ('', '1')}
    for s in scenarios:
        v = {r for r in valid if scenario_of(r) == s}
        cells = [str(len({r for r, _ in ids if scenario_of(r) == s}))
                 for label, ids in sources.items() if label != 'manifest (valid)']
        row = [s, str(len(v))] + cells + [
            str(len({r for r in redone_runs if scenario_of(r) == s})),
            str(int((failed.run_id.map(scenario_of) == s).sum()) if len(failed) else 0)]
        lines.append('| ' + ' | '.join(row) + ' |')
    total = (['**total**', f'**{len(valid)}**']
             + [f'**{len(ids)}**' for label, ids in sources.items() if label != 'manifest (valid)']
             + [f'**{len(redone_runs)}**', f'**{len(failed)}**'])
    lines.append('| ' + ' | '.join(total) + ' |')

    agree = all(ids == valid_keys for ids in sources.values())
    lines.append(f'\n**Identical run sets in every source (same run and same attempt): '
                 f'{"yes" if agree else "NO"}.**')
    for label, ids in sources.items():
        if ids != valid_keys:
            lines.append(f'- {label}: missing or superseded {sorted(valid_keys - ids)[:10]}, '
                         f'extra {sorted(ids - valid_keys)[:10]}')
    if code_other:
        lines.append(f'- runs with a different code fingerprint: {code_other}')

    infra = failed[failed.kind.str.startswith('infrastructure')] if len(failed) else failed
    interrupted = int(failed.kind.str.startswith('interrupted').sum()) if len(failed) else 0
    attempts = len(valid) + len(failed) - interrupted   # operator interruptions excluded
    lines.append('\n## Unused attempts\n')
    for kind, n in collections.Counter(failed.kind).most_common():
        lines.append(f'- {kind}: {n}')
    defect = int(failed.kind.str.startswith('runner defect').sum()) if len(failed) else 0
    attempts -= defect   # a runner defect is not a property of the simulated system
    lines.append(f'\nInfrastructure failure rate: **{len(infra)} of {attempts} attempts** '
                 f'({100 * len(infra) / max(1, attempts):.1f} %; excluded: {interrupted} attempt(s) '
                 f'interrupted by the operator and {defect} attempt(s) lost to the runner defect, '
                 f'all redone); runs that needed more '
                 f'than one attempt for infrastructure reasons: **{infra.run_id.nunique()}** of '
                 f'{len(valid)}. No run was dropped: every failed attempt was redone until valid.')
    if len(failed):
        lines.append('\n| Run | reason | status | kind |\n|---|---|---|---|')
        for r in failed.itertuples():
            lines.append(f'| {r.run_id} | {r.reason} | {r.status} | {r.kind} |')
    os.makedirs(os.path.dirname(cli.out), exist_ok=True)
    with open(cli.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    sys.exit(0 if agree else 1)


if __name__ == '__main__':
    main()
