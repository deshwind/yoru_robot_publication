#!/usr/bin/env python3
"""Live view of the current gentle session, for a terminal.

  watch -n 10 python3 evaluation/scripts/show_progress.py      # refreshes every 10 s
  python3 evaluation/scripts/show_progress.py                  # one snapshot

Reads evaluation/progress/live.log ([gentle] lines of the latest session) and the
last line of evaluation/progress/host_monitor.log. Read-only: it starts nothing.
"""

import datetime
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
LIVE = os.path.join(ROOT, 'evaluation', 'progress', 'live.log')
MONITOR = os.path.join(ROOT, 'evaluation', 'progress', 'host_monitor.log')


def latest_session(lines):
    start = max((i for i, l in enumerate(lines) if '[gentle] session start' in l), default=None)
    return [] if start is None else lines[start:]


def main():
    if not os.path.isfile(LIVE):
        print('no live log yet')
        return
    with open(LIVE, encoding='utf-8', errors='replace') as f:
        lines = [l.rstrip('\n') for l in f]
    session = latest_session(lines)
    if not session:
        print('no gentle session found in the live log')
        return
    head = session[0]
    m = re.search(r'(\d\d:\d\d:\d\d) \[gentle\] session start: tag=(\S+), (\d+) of (\d+) runs to do; '
                  r'budget (\S+) min', head)
    t0, tag, todo, total, budget = m.groups() if m else ('?', '?', '0', '0', '60')
    todo = int(todo)
    runs, current, ended = [], None, None
    for line in session[1:]:
        r = re.search(r'(\d\d:\d\d:\d\d) \[gentle\] run (\d+)/(\d+): (\S+) seed (\d+)', line)
        if r:
            current = {'start': r.group(1), 'n': int(r.group(2)), 'run': f'{r.group(4)}/{r.group(5)}'}
            continue
        ok = re.search(r'(\d\d:\d\d:\d\d) \[gentle\]   ok: (\S+) (\S+) at ([\d.]+) s sim, RTF ([\d.]+)', line)
        bad = re.search(r'(\d\d:\d\d:\d\d) \[gentle\]   NOT ok: (\S+)', line)
        peak = re.search(r'peak ([\d.]+) C', line)
        if (ok or bad) and current:
            current.update(end=(ok or bad).group(1),
                           result=(f'{ok.group(2)} {ok.group(3)} at {ok.group(4)} s' if ok
                                   else f'FAILED: {bad.group(2)}'),
                           rtf=ok.group(5) if ok else '-')
            runs.append(current)
        elif peak and runs:
            runs[-1]['peak'] = peak.group(1)
        if '[gentle] session end' in line:
            ended = line
    now = datetime.datetime.now()
    print(f'Yoru Phase C  |  run set {tag}  |  {now:%H:%M:%S}')
    print(f'session started {t0}, budget {budget} min\n')
    print(f'{"#":>3}  {"run":8} {"started":8}  {"result":32} {"RTF":>5} {"peak C":>6}')
    for r in runs:
        print(f'{r["n"]:>3}  {r["run"]:8} {r["start"]:8}  {r["result"]:32} {r["rtf"]:>5} '
              f'{r.get("peak", "-"):>6}')
    done = sum(1 for r in runs if not r['result'].startswith('FAILED'))
    if ended:
        print(f'\nSESSION ENDED: {ended.split("[gentle] ", 1)[1]}')
    else:
        if current and current not in runs:
            since = datetime.datetime.combine(now.date(), datetime.time.fromisoformat(current['start']))
            print(f'{current["n"]:>3}  {current["run"]:8} {current["start"]:8}  '
                  f'running for {int((now - since).total_seconds() // 60)} min {int((now - since).total_seconds() % 60)} s')
        elif runs:
            print('     ... cooling down before the next run')
        left = todo - done
        if runs:
            first = datetime.datetime.combine(now.date(), datetime.time.fromisoformat(runs[0]['start']))
            per = (now - first).total_seconds() / max(len(runs), 1)
            eta = now + datetime.timedelta(seconds=per * left)
            print(f'\n{done} of {todo} done this session, {left} to go; '
                  f'about {per / 60:.1f} min per run -> finish about {eta:%H:%M}')
    if os.path.isfile(MONITOR):
        with open(MONITOR, encoding='utf-8', errors='replace') as f:
            last = [l for l in f if l[:2].isdigit()][-1:]
        if last:
            p = [x.strip() for x in last[0].split('|')]
            if len(p) >= 9:
                print(f'\nlaptop ({p[0]}): thermal zone {p[7]} C, CPU performance {p[1]} %, '
                      f'Windows CPU {p[2]} %, throttling limit {p[8]} % (100 = none)')
    print('\nstop after the current run:  touch evaluation/progress/STOP')


if __name__ == '__main__':
    main()
