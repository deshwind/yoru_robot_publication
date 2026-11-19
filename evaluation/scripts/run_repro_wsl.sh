#!/usr/bin/env bash
# Reproduction sample on the same laptop under WSL2: every scenario x seeds 0-2,
# baseline configuration (+ YOLO torch_threads=2 from eval_base.yaml).
# Detached so it survives the terminal; progress goes to evaluation/progress/live.log.
#   bash evaluation/scripts/run_repro_wsl.sh
set -o pipefail   # no -u: ROS setup.bash reads unset variables
cd "$(dirname "$0")/../.."
source /opt/ros/humble/setup.bash
source install/setup.bash
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA      # Gazebo rendering on the NVIDIA GPU
LIVE=evaluation/progress/live.log
mkdir -p evaluation/data/repro
echo "$(date +%T) [repro] start: all scenarios x seeds 0,1,2 (45 runs), tag repro_wsl" >> "$LIVE"
python3 -u evaluation/scripts/run_batch.py --scenarios all --seed-list 0,1,2 --tag repro_wsl \
    --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing 2>&1 \
  | tee -a evaluation/data/repro/batch.log \
  | while IFS= read -r line; do echo "$(date +%T) [repro] $line" >> "$LIVE"; done
echo "$(date +%T) [repro] batch runner exited" >> "$LIVE"
