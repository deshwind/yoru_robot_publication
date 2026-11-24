#!/usr/bin/env python3
"""Why did Nav2 not come up? Analysis of every nav2_not_ready attempt (2026-11-24).

For each failed attempt under evaluation/data/runs_invalid/ (and, for comparison, every
valid run under evaluation/data/{variants,repro}/), reads launch.log and reports:
which Nav2 lifecycle managers became active, which node each manager was configuring or
activating last, which service replies were lost ("failed to send response to ..."),
and how many wall seconds after the launch the runner gave up.

  python3 evaluation/scripts/nav2_startup_failures.py

Finding (evidence/README.md, Phase C): the failures are stuck, not slow. A lifecycle
change_state reply of map_server or amcl is lost, so localization never activates and the
navigation manager waits on planner_server (it needs map -> odom). Valid runs have both
managers active within 25.8 s of the launch; failed ones are still stuck 35-47 s after it.
"""
import re, glob, os, json, statistics as st, collections, sys

ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
TS=re.compile(r'\[(\d{10}\.\d+)\]')
def analyse(log):
    t0=None; ready={}; waits=collections.Counter(); last={}; sigint=None; fsr=collections.Counter(); spawn=None
    for line in open(log, errors='replace'):
        m=TS.search(line)
        t=float(m.group(1)) if m else None
        if t and t0 is None: t0=t
        if 'Managed nodes are active' in line and t:
            mgr='localization' if 'localization' in line else 'navigation'; ready.setdefault(mgr, t)
        w=re.search(r'\[lifecycle_manager_(\w+)\]: Waiting for service (\S+)/get_state', line)
        if w: waits[(w.group(1), w.group(2))]+=1
        a=re.search(r'\[lifecycle_manager_(\w+)\]: .*?(Configuring|Activating) (\w+)', line)
        if a and t: last[a.group(1)]=(a.group(2), a.group(3), t)
        f=re.search(r'failed to send response to (\S+) ', line)
        if f: fsr[f.group(1)]+=1
        if 'Successfully spawned entity' in line and t: spawn=t
        if "sending signal 'SIGINT'" in line and sigint is None:
            sigint=t if t else (max(x for x in [t0]+[v for v in ready.values()] if x))
    # SIGINT lines have no epoch; use last timestamp seen before it
    return t0, ready, waits, last, fsr, spawn
def last_ts_before_sigint(log):
    lt=None
    for line in open(log, errors='replace'):
        if "sending signal 'SIGINT'" in line: return lt
        m=TS.search(line)
        if m: lt=float(m.group(1))
    return lt
fails=[d for d in glob.glob(ROOT+'/runs_invalid/**/run_info.json', recursive=True) if json.load(open(d)).get('status')=='nav2_not_ready']
print(f'failed nav2_not_ready attempts found: {len(fails)}')
stuck=collections.Counter(); notready=collections.Counter(); rows=[]
for p in fails:
    log=os.path.join(os.path.dirname(p),'launch.log')
    t0,ready,waits,last,fsr,spawn=analyse(log); end=last_ts_before_sigint(log)
    missing=[m for m in ('localization','navigation') if m not in ready]
    for m in missing: notready[m]+=1
    top=waits.most_common(1)[0] if waits else None
    if top: stuck[top[0]]+=1
    rows.append((os.path.relpath(os.path.dirname(p),ROOT)[-38:], missing, top, {k:(v[0],v[1]) for k,v in last.items()}, dict(fsr), round(end-t0,1) if end and t0 else None))
for r in rows: print(r)
print('\nmanagers not ready at abort:', dict(notready))
print('most-waited-for service (manager, service):', stuck.most_common(5))
# successful runs: wall seconds from launch start to both managers active
ok=[]
for p in glob.glob(ROOT+'/variants/**/run_info.json', recursive=True)+glob.glob(ROOT+'/repro/**/run_info.json', recursive=True):
    if json.load(open(p)).get('status')!='ok': continue
    t0,ready,*_=analyse(os.path.join(os.path.dirname(p),'launch.log'))
    if len(ready)==2: ok.append(max(ready.values())-t0)
print(f'\nsuccessful runs: both managers active after {st.median(ok):.1f} s wall (median), p90 {sorted(ok)[int(0.9*len(ok))]:.1f} s, max {max(ok):.1f} s, n={len(ok)}')
