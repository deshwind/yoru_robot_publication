#!/usr/bin/env bash
# One gentle Phase C session (detached): sources ROS, renders Gazebo on the
# NVIDIA GPU and runs gentle_batch.py with the given arguments.
#   setsid nohup bash evaluation/scripts/run_phase_c_session.sh <gentle_batch args...> &
set -o pipefail   # no -u: ROS setup.bash reads unset variables
cd "$(dirname "$0")/../.."
source /opt/ros/humble/setup.bash
source install/setup.bash
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
mkdir -p evaluation/progress
python3 -u evaluation/scripts/gentle_batch.py "$@" >> evaluation/progress/gentle_session.out 2>&1
