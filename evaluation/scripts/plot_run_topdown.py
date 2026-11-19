#!/usr/bin/env python3
"""Top-down figure of one run, drawn from its bag over the saved simulation map.

Shows the robot's path (Gazebo ground truth), every person inside the building,
the violator, the CCTV cameras and the cctv1 camera spot, and marks where the
robot was at each escalation-stage change. Positions and the bag-to-sim time
mapping come from extract_metrics.RunData, the same code as the published
metrics.

  python3 evaluation/scripts/plot_run_topdown.py <run_dir> <out_prefix>
      -> <out_prefix>.png and <out_prefix>.pdf
"""

import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import yaml  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_metrics as em  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
MAP = os.path.join(ROOT, 'maps', 'sim', 'main_map.yaml')
SPOTS = os.path.join(ROOT, 'maps', 'sim', 'cameras.json')
CCTV = {'CCTV 1': (5.8, 0.0, np.pi), 'CCTV 2': (-5.8, 0.0, 0.0)}   # eval_two_room.world
INSIDE = (-6.0, 6.0, -4.0, 4.0)
SHORT = {'PA_WARNING': 'S1 PA warning', 'APPROACH': 'S2 approach',
         'DIRECT_WARNING': 'S3 direct warning', 'MONITORING': 'outcome',
         'LOG_ESCALATION': 'S4 log', 'SAFE_STOP': 'safe stop', 'RETURN_TO_BASE': 'return'}


def load_map():
    with open(MAP) as f:
        meta = yaml.safe_load(f)
    img = plt.imread(os.path.join(os.path.dirname(MAP), meta['image']))
    h, w = img.shape[:2]
    x0, y0 = meta['origin'][:2]
    res = meta['resolution']
    return img, (x0, x0 + w * res, y0, y0 + h * res)


def inside(track):
    x0, x1, y0, y1 = INSIDE
    return [p for p in track if x0 < p[1] < x1 and y0 < p[2] < y1]


def main():
    run_dir, out = sys.argv[1], sys.argv[2]
    data = em.RunData(os.path.join(run_dir, 'bag'))
    with open(os.path.join(run_dir, 'run_info.json')) as f:
        info = json.load(f)
    violator = next((g.get('violator') for g in data.gt if g.get('violator')), None)

    fig, ax = plt.subplots(figsize=(8.4, 5.8))
    img, extent = load_map()
    ax.imshow(img, cmap='gray', extent=extent, origin='upper', vmin=0, vmax=255, alpha=0.55)

    for name in em.PEOPLE:
        track = inside(data.positions(name))
        if not track:
            continue
        xs, ys = [p[1] for p in track], [p[2] for p in track]
        if name == violator:
            ax.plot(xs, ys, color='#c0392b', lw=2.2, label=f'violator ({name})', zorder=4)
            ax.plot(xs[-1], ys[-1], 'o', color='#c0392b', ms=9, zorder=5)
        else:
            ax.plot(xs, ys, color='#7f8c8d', lw=1.2, ls='--', label=f'{name}', zorder=3)
            ax.plot(xs[-1], ys[-1], 'o', color='#7f8c8d', ms=6, zorder=3)

    robot = data.positions('yoru_robot')
    if robot:
        rx, ry = [p[1] for p in robot], [p[2] for p in robot]
        ax.plot(rx, ry, color='#1f5fa8', lw=2.4, label='robot path', zorder=5)
        ax.plot(rx[0], ry[0], 's', color='#1f5fa8', ms=9, zorder=6)
        ax.annotate('robot base', (rx[0], ry[0]), xytext=(6, -14), textcoords='offset points',
                    fontsize=8, color='#1f5fa8')
        # Stage changes only: a self-transition (e.g. MONITORING -> MONITORING,
        # reason cooldown_end) is bookkeeping, not an escalation step
        changes = [ev for ev in data.fsm if ev['new_state'] != ev['previous_state']]
        for i, ev in enumerate(changes):
            pos = data.position_at('yoru_robot', ev['stamp'])
            if pos is None:
                continue
            label = SHORT.get(ev['new_state'], ev['new_state'])
            if ev['new_state'] == 'MONITORING':
                label = f"outcome: {ev['reason']}"
            ax.plot(*pos, 'D', color='#f39c12', mec='k', ms=7, zorder=7)
            ax.annotate(f"{label}\n{ev['stamp']:.1f} s", pos,
                        xytext=(8, 10 + 18 * (i % 2)), textcoords='offset points', fontsize=7.5,
                        bbox=dict(boxstyle='round,pad=0.2', fc='white', ec='#f39c12', lw=0.8),
                        zorder=8)

    for name, (x, y, yaw) in CCTV.items():
        ax.plot(x, y, marker=(3, 0, np.degrees(yaw) - 90), color='#16a085', ms=13, zorder=6)
        ax.annotate(name, (x, y), xytext=(-14 if x > 0 else 4, 10), textcoords='offset points',
                    fontsize=8, color='#16a085')
    with open(SPOTS) as f:
        for spot in json.load(f):
            ax.plot(spot['x'], spot['y'], '*', color='#16a085', ms=15, mec='k', zorder=6)
            ax.annotate(f"{spot['id']} spot", (spot['x'], spot['y']), xytext=(6, -14),
                        textcoords='offset points', fontsize=8, color='#16a085')

    ax.set_xlim(-6.4, 6.4)
    ax.set_ylim(-4.4, 4.4)
    ax.set_aspect('equal')
    ax.set_xlabel('x (m)')
    ax.set_ylabel('y (m)')
    ax.set_title(f"{info.get('scenario')} seed {info.get('seed')}: outcome {info.get('outcome')} "
                 f"({info.get('outcome_stage')}) at {info.get('outcome_sim_t')} s sim", fontsize=10)
    ax.legend(loc='upper left', fontsize=7.5, framealpha=0.9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    for ext in ('png', 'pdf'):
        fig.savefig(f'{out}.{ext}', dpi=200)
    print(f'-> {out}.png / .pdf')


if __name__ == '__main__':
    main()
