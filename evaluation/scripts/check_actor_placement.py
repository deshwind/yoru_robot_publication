#!/usr/bin/env python3
"""Post-hoc check that every run's simulated people were actually in the scene.

human_actor_node sends each person's placement (teleport) once; if that
message is lost, the person stays parked outside the building and the
scenario never happens (found 2026-10-12 in K seed 1). For each run, every
person of the layout must be inside the building (|x| < 6, |y| < 4) in the
ground-truth heartbeat at the violation/confounder onset.

Usage: python3 evaluation/scripts/check_actor_placement.py [--manifest M] [--csv out.csv]
Exit code 1 if any valid run fails the check.
"""
import argparse
import json
import os
import sys

import pandas as pd
from rosbags.rosbag2 import Reader
from rosbags.typesys import Stores, get_typestore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE = get_typestore(Stores.ROS2_HUMBLE)


def inside(x, y):
    return abs(x) < 6.0 and abs(y) < 4.0


def check(run_dir):
    layout, onset, beats = None, None, []
    with Reader(os.path.join(run_dir, 'bag')) as rd:
        conns = [c for c in rd.connections
                 if c.topic in ('/compliance/actor_events', '/compliance/scenario_ground_truth')]
        for c, _, raw in rd.messages(connections=conns):
            d = json.loads(STORE.deserialize_cdr(raw, c.msgtype).data)
            if c.topic == '/compliance/actor_events' and d.get('event') == 'layout':
                layout = d
            elif d.get('event') in ('violation_onset', 'confounder_onset') and onset is None:
                onset = d['stamp']
            elif d.get('event') == 'state':
                beats.append(d)
    if layout is None or onset is None:
        return False, 'no layout or no onset recorded'
    after = [b for b in beats if b['stamp'] >= onset]
    if not after:
        return False, 'no heartbeat after the onset'
    actors = after[0].get('actors', [])
    outside = [f"{a['id']} at ({a['x']:.1f}, {a['y']:.1f})" for a in actors if not inside(a['x'], a['y'])]
    missing = {p['actor'] for p in layout['persons']} - {a['id'] for a in actors}
    if outside or missing:
        return False, '; '.join(outside + [f'{m} missing' for m in missing])
    return True, f"{len(actors)} person(s) in the scene at onset"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', default=os.path.join(ROOT, 'evaluation', 'data', 'manifest.csv'))
    ap.add_argument('--csv')
    cli = ap.parse_args()
    table = pd.read_csv(cli.manifest, dtype=str, keep_default_na=False)
    table = table.drop_duplicates('run_id', keep='last')
    rows = []
    for r in table[table.status == 'ok'].itertuples():
        ok, detail = check(os.path.join(ROOT, r.run_dir))
        rows.append({'run_id': r.run_id, 'tag': r.tag, 'scenario': r.scenario, 'seed': r.seed,
                     'actors_placed': ok, 'detail': detail, 'run_dir': r.run_dir})
    out = pd.DataFrame(rows)
    if cli.csv:
        out.to_csv(cli.csv, index=False)
    bad = out[~out.actors_placed]
    print(f'{len(out)} valid runs checked; {len(bad)} with people not in the scene')
    for r in bad.itertuples():
        print(f'  {r.run_id}: {r.detail}')
    sys.exit(1 if len(bad) else 0)


if __name__ == '__main__':
    main()
