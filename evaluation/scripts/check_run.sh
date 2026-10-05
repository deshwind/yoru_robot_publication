#!/usr/bin/env bash
# One headless evaluation run with bag recording, then a bag summary.
#
#   bash evaluation/scripts/check_run.sh <out_dir> <overlay.yaml> <duration_s> [extra launch args...]
#
# The overlay is copied into <out_dir>; the incident log is redirected into
# <out_dir>/incident_logs. Uses the evaluation world with the simulated
# humans (use_actors:=true), sim time for all decision timing.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUN="$(realpath -m "$1")"; OVERLAY="$2"; DURATION="${3:-180}"; shift 3
rm -rf "$RUN" && mkdir -p "$RUN"
{
    cat "$OVERLAY"
    printf '\nincident_logger_node:\n  ros__parameters:\n    log_dir: %s/incident_logs\n' "$RUN"
} > "$RUN/overlay.yaml"

source /opt/ros/humble/setup.bash
source "$ROOT/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID_EVAL:-88}"
unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT

cd "$RUN"
setsid ros2 launch yoru_bringup sim_full.launch.py \
    gui:=false rviz:=false open_browser:=false use_joystick:=false \
    world:="$ROOT/install/yoru_bringup/share/yoru_bringup/worlds/eval_two_room.world" \
    use_actors:=true use_ros_clock:=true overlay_params:="$RUN/overlay.yaml" \
    bag_path:="$RUN/bag" "$@" > "$RUN/launch.log" 2>&1 &
LAUNCH_PID=$!
echo "run $RUN: launched (pid $LAUNCH_PID) for ${DURATION}s"
sleep "$DURATION"

kill -INT -- -"$LAUNCH_PID" 2>/dev/null
for _ in $(seq 1 30); do kill -0 "$LAUNCH_PID" 2>/dev/null || break; sleep 1; done
kill -KILL -- -"$LAUNCH_PID" 2>/dev/null
sleep 2

python3 "$ROOT/evaluation/scripts/bag_summary.py" "$RUN/bag" 2>&1 \
    | grep -v rosbag2_storage > "$RUN/bag_summary.txt"
echo "summary: $RUN/bag_summary.txt"
