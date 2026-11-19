#!/usr/bin/env python3
"""Progress and health snapshot of simulation runs on this machine.

Writes evaluation/progress/STATUS.md (overwritten) and appends one line to
evaluation/progress/watchdog.log. Copies every run-set manifest under
evaluation/data/ into evaluation/progress/manifests/ so the progress can be
pushed (evaluation/data/ itself is git-ignored).

  python3 evaluation/scripts/progress_status.py      # exit 1 if a problem was found

Problems flagged: Gazebo running with no batch runner (orphan); more than one
Gazebo server; the last 3 attempts all failed; RTF of the last run below 0.4;
less than 1 GB of memory or 5 GB of disk available.
"""

import csv
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DATA = os.path.join(ROOT, 'evaluation', 'data')
OUT = os.path.join(ROOT, 'evaluation', 'progress')
MIN_RTF = 0.4


def processes():
    out = subprocess.run(['ps', '-eo', 'pid=,etime=,comm=,args='],
                         capture_output=True, text=True).stdout
    procs = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            procs.append({'pid': parts[0], 'etime': parts[1], 'comm': parts[2], 'args': parts[3]})
    return procs


def resources():
    mem = {}
    for line in open('/proc/meminfo'):
        key, val = line.split(':')
        mem[key] = int(val.split()[0]) // 1024
    disk = shutil.disk_usage(ROOT)
    return {'mem_avail_mb': mem['MemAvailable'], 'mem_total_mb': mem['MemTotal'],
            'swap_used_mb': mem['SwapTotal'] - mem['SwapFree'],
            'disk_free_gb': disk.free // 2**30,
            'load': open('/proc/loadavg').read().split()[0]}


def manifests():
    found = sorted(glob.glob(os.path.join(DATA, '**', 'manifest.csv'), recursive=True))
    sets = []
    for path in found:
        with open(path) as f:
            rows = list(csv.DictReader(f))
        sets.append((os.path.relpath(path, DATA), rows))
    return sets


def newest_run_info():
    infos = glob.glob(os.path.join(DATA, '**', 'run_info.json'), recursive=True)
    infos = [p for p in infos if '/runs_invalid/' not in p]
    if not infos:
        return None, None
    path = max(infos, key=os.path.getmtime)
    with open(path) as f:
        return path, json.load(f)


def newest_launch_log():
    logs = glob.glob(os.path.join(DATA, '**', 'launch.log'), recursive=True)
    return max(logs, key=os.path.getmtime) if logs else None


def log_errors(path, limit=6):
    """Real failures in a launch log (not the SIGINT exits of a normal stop)."""
    errors = []
    with open(path, errors='replace') as f:
        for line in f:
            if ('process has died' in line and 'exit code -2' not in line
                    and 'exit code -15' not in line
                 and 'exit code -9' not in line) or 'Spawn service failed' in line \
                    or 'Traceback' in line:
                errors.append(line.strip()[:200])
    return errors[-limit:]


def main():
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    os.makedirs(os.path.join(OUT, 'manifests'), exist_ok=True)
    procs = processes()
    runners = [p for p in procs if p['comm'].startswith('python') and 'run_batch.py' in p['args']]
    gazebo = [p for p in procs if p['comm'] == 'gzserver']
    res = resources()
    sets = manifests()
    info_path, info = newest_run_info()
    launch_log = newest_launch_log()
    invalid = len(glob.glob(os.path.join(DATA, 'runs_invalid', '**', 'run_info.json'), recursive=True))

    problems = []
    if gazebo and not runners:
        problems.append(f'{len(gazebo)} Gazebo server(s) running with no batch runner (orphaned)')
    if len(gazebo) > 1:
        problems.append(f'{len(gazebo)} Gazebo servers running (one escaped cleanup)')
    if res['mem_avail_mb'] < 1024:
        problems.append(f"only {res['mem_avail_mb']} MB of memory available")
    if res['disk_free_gb'] < 5:
        problems.append(f"only {res['disk_free_gb']} GB of disk free")
    attempts = []
    for _, rows in sets:
        attempts += rows
    attempts.sort(key=lambda r: r.get('start_wall', ''))
    last3 = [r['status'] for r in attempts[-3:]]
    if len(last3) == 3 and 'ok' not in last3:
        problems.append(f'the last 3 recorded runs all failed ({", ".join(last3)})')
    if info and info.get('rtf') not in (None, '') and float(info['rtf']) < MIN_RTF:
        problems.append(f"last run's real-time factor {info['rtf']} is below {MIN_RTF}")

    for rel, _ in sets:
        if rel == 'manifest.csv':      # the baseline manifest is already tracked
            continue
        dest = os.path.join(OUT, 'manifests', rel.replace(os.sep, '__'))
        shutil.copyfile(os.path.join(DATA, rel), dest)

    lines = [f'# Simulation progress: {now}', '',
             f"**Health: {'PROBLEM' if problems else 'OK'}**", '']
    lines += [f'- {p}' for p in problems] + ([''] if problems else [])
    if runners:
        lines.append(f"Batch runner: running for {runners[0]['etime']} "
                     f"(`{runners[0]['args'].split('run_batch.py', 1)[1].strip()[:150]}`)")
    else:
        lines.append('Batch runner: not running')
    lines.append(f"Gazebo servers: {len(gazebo)}" + (f" (up {gazebo[0]['etime']})" if gazebo else ''))
    lines.append(f"Memory available: {res['mem_avail_mb']} / {res['mem_total_mb']} MB, "
                 f"swap used {res['swap_used_mb']} MB, disk free {res['disk_free_gb']} GB, "
                 f"load {res['load']}")
    lines.append(f'Failed attempts set aside (runs_invalid): {invalid}')
    lines.append('')
    lines.append('## Run sets')
    lines.append('')
    lines.append('| Manifest | rows | ok | other statuses |')
    lines.append('|---|---|---|---|')
    for rel, rows in sets:
        ok = sum(r['status'] == 'ok' for r in rows)
        other = {}
        for r in rows:
            if r['status'] != 'ok':
                other[r['status']] = other.get(r['status'], 0) + 1
        lines.append(f"| {rel} | {len(rows)} | {ok} | "
                     f"{', '.join(f'{k} {v}' for k, v in sorted(other.items())) or '-'} |")
    lines.append('')
    lines.append('## Latest runs (all run sets, newest last)')
    lines.append('')
    lines.append('| run | status | outcome | stage | sim s | wall s | RTF | start |')
    lines.append('|---|---|---|---|---|---|---|---|')
    for r in attempts[-8:]:
        lines.append(f"| {r['run_id']} | {r['status']} | {r['outcome']} | {r['outcome_stage']} | "
                     f"{r['sim_s']} | {r['wall_s']} | {r['rtf']} | {r['start_wall']} |")
    lines.append('')
    if info:
        lines.append(f"Newest run: `{os.path.relpath(info_path, ROOT)}`: status {info.get('status')}, "
                     f"RTF {info.get('rtf')}, sim {info.get('sim_s')} s, wall {info.get('wall_s')} s")
    if launch_log:
        errs = log_errors(launch_log)
        lines.append('')
        lines.append(f'Newest launch log: `{os.path.relpath(launch_log, ROOT)}`')
        if errs:
            lines.append('')
            lines.append('```')
            lines += errs
            lines.append('```')
    with open(os.path.join(OUT, 'STATUS.md'), 'w') as f:
        f.write('\n'.join(lines) + '\n')

    summary = (f"{now} health={'PROBLEM' if problems else 'OK'} runner={'yes' if runners else 'no'} "
               f"gazebo={len(gazebo)} runs_ok={sum(r['status'] == 'ok' for r in attempts)}/{len(attempts)} "
               f"invalid={invalid} mem_avail={res['mem_avail_mb']}MB disk={res['disk_free_gb']}G"
               + (f" | {'; '.join(problems)}" if problems else ''))
    with open(os.path.join(OUT, 'watchdog.log'), 'a') as f:
        f.write(summary + '\n')
    print(summary)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
