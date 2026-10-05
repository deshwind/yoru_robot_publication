#!/usr/bin/env bash
# Point the simulation configuration at THIS clone of the repository.
#
# A few configuration files hold absolute paths to the maps, camera spots,
# dashboard data and YOLO weights (inherited from V2's single-machine
# setup). Run this once after cloning anywhere other than
# ~/Yoru_bot_publication, then rebuild:
#   bash evaluation/scripts/configure_paths.sh && colcon build --symlink-install
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FILES=(src/yoru_bringup/config/yoru_sim.yaml
       src/yoru_bringup/launch/sim.launch.py
       src/yoru_bringup/launch/sim_full.launch.py)
cd "$ROOT"
for f in "${FILES[@]}"; do
    sed -i -e "s#/home/desh/Yoru_bot_publication#$ROOT#g" \
           -e "s#~/Yoru_bot_publication#$ROOT#g" "$f"
done
echo "configured for $ROOT:"
grep -n "$ROOT" "${FILES[@]}" | sed "s#$ROOT#<repo>#g"
