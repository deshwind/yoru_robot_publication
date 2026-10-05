#!/usr/bin/env python3
"""Phase 0 evidence: summarise the pre-existing incident logs.

Reads the copies in evidence/phase0/incident_logs/ (originals in
~/compliance_robot_logs/, checksums in evidence/README.md) and reports the
confidence values and outcomes actually logged.

Usage: python3 evaluation/scripts/phase0_incident_summary.py
"""

import collections
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_GLOB = os.path.join(ROOT, 'evidence', 'phase0', 'incident_logs', '*.jsonl')
SIM_ROOMS = ('room_a', 'sim_room_1')  # rooms used by the Gazebo worlds


def main():
    records = []
    for path in sorted(glob.glob(LOG_GLOB)):
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except ValueError:
                    pass

    sim = [r for r in records if r.get('room_id') in SIM_ROOMS]
    conf = [r.get('confidence') for r in records
            if isinstance(r.get('confidence'), (int, float))]
    print(f'incident records: {len(records)} total, {len(sim)} simulation '
          f'(rooms {", ".join(SIM_ROOMS)})')
    print(f'minimum logged confidence (all records): {min(conf):.3f}')
    print(f'records with confidence < 0.600: '
          f'{sum(1 for c in conf if c < 0.6)}')

    print('\nsimulation records by (event_class, confidence, C5_support, fp_risk):')
    keyed = collections.Counter(
        (r.get('event_class'), r.get('confidence'),
         (r.get('criteria') or {}).get('C5_support'),
         (r.get('criteria') or {}).get('C7_fp_risk')) for r in sim)
    for key, n in keyed.most_common():
        print(f'  {n:4d}  {key}')

    print('\nsimulation records by (stage_reached, outcome):')
    for key, n in collections.Counter(
            (r.get('stage_reached'), r.get('outcome')) for r in sim).most_common():
        print(f'  {n:4d}  {key}')

    print('\nall records by (stage_reached, outcome):')
    for key, n in collections.Counter(
            (r.get('stage_reached'), r.get('outcome')) for r in records).most_common():
        print(f'  {n:4d}  {key}')


if __name__ == '__main__':
    main()
