#!/usr/bin/env python3
"""Storyboard figure from capture_pictures.py output: one row per snapshot,
one column per camera.

  python3 evaluation/scripts/make_storyboard.py <pictures_dir> <out_prefix> \
      [--rows 03 04 05 06 08] [--cams overview_oblique cctv1_yolo robot_camera]
"""
import argparse
import csv
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

TITLES = {'overview_oblique': 'Overview (documentation camera)',
          'overview_top': 'Top-down (documentation camera)',
          'cctv1_yolo': 'CCTV 1 + YOLO boxes', 'cctv2_yolo': 'CCTV 2 + YOLO boxes',
          'cctv1_raw': 'CCTV 1', 'cctv2_raw': 'CCTV 2', 'robot_camera': 'Robot camera'}

ap = argparse.ArgumentParser()
ap.add_argument('pictures')
ap.add_argument('out')
ap.add_argument('--rows', nargs='*', default=['03', '04', '05', '06', '08'])
ap.add_argument('--cams', nargs='*', default=['overview_oblique', 'cctv1_yolo', 'robot_camera'])
cli = ap.parse_args()
with open(os.path.join(cli.pictures, 'index.csv')) as f:
    index = list(csv.DictReader(f))
fig, axes = plt.subplots(len(cli.rows), len(cli.cams),
                         figsize=(3.6 * len(cli.cams), 2.35 * len(cli.rows)),
                         gridspec_kw={'width_ratios': [1.6 if c.startswith('overview') else 1
                                                       for c in cli.cams]})
for i, row in enumerate(cli.rows):
    for j, cam in enumerate(cli.cams):
        ax = axes[i][j]
        entry = next(e for e in index if e['file'].startswith(row + '_') and e['camera'] == cam)
        ax.imshow(plt.imread(os.path.join(cli.pictures, entry['file'])))
        ax.set_xticks([])
        ax.set_yticks([])
        if i == 0:
            ax.set_title(TITLES.get(cam, cam), fontsize=9)
        if j == 0:
            trig = entry['trigger'].replace(' -> ', '\n-> ')
            ax.set_ylabel(f"{float(entry['sim_time_s']):.1f} s\n{trig}", fontsize=7.5)
fig.tight_layout()
for ext in ('png', 'pdf'):
    fig.savefig(f'{cli.out}.{ext}', dpi=170)
print(f'-> {cli.out}.png / .pdf')
