#!/usr/bin/env bash
# Phase 2 evidence: one headless Scenario A run with every instrumentation
# topic recorded, then a bag summary. Uses yoru_sim.yaml timings unchanged;
# the overlay only redirects the incident log, silences audio playback and
# switches the decision nodes to sim time.
#
#   bash evaluation/scripts/phase2_check_run.sh [duration_s]
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DURATION="${1:-170}"
RUN="${RUN_DIR:-$ROOT/evidence/phase2/check_run}"
rm -rf "$RUN" && mkdir -p "$RUN"

cat > "$RUN/overlay.yaml" <<EOF
# Phase 2 check-run overlay (applied after yoru_sim.yaml)
incident_logger_node:
  ros__parameters:
    log_dir: $RUN/incident_logs
incident_emailer_node:
  ros__parameters:
    enabled: false
audio_warning_node:
  ros__parameters:
    use_audio: false
scenario_publisher_node:
  ros__parameters:
    scenario_id: phase2_check_A
    seed: 0
EOF

source /opt/ros/humble/setup.bash
source "$ROOT/install/setup.bash"
# Isolated DDS domain, plain multicast discovery (no Pi discovery server)
export ROS_DOMAIN_ID=88
unset ROS_DISCOVERY_SERVER ROS_SUPER_CLIENT

cd "$RUN"
setsid ros2 launch yoru_bringup sim_full.launch.py \
    gui:=false rviz:=false open_browser:=false use_joystick:=false \
    use_ros_clock:=true overlay_params:="$RUN/overlay.yaml" \
    bag_path:="$RUN/bag" > "$RUN/launch.log" 2>&1 &
LAUNCH_PID=$!
echo "launched (pid $LAUNCH_PID), recording for ${DURATION}s"
sleep "$DURATION"

# Graceful stop so the bag is finalised, then make sure nothing survives
kill -INT -- -"$LAUNCH_PID" 2>/dev/null
for _ in $(seq 1 30); do kill -0 "$LAUNCH_PID" 2>/dev/null || break; sleep 1; done
kill -KILL -- -"$LAUNCH_PID" 2>/dev/null
sleep 2

python3 "$ROOT/evaluation/scripts/bag_summary.py" "$RUN/bag" > "$RUN/bag_summary.txt" 2>&1
cat "$RUN/bag_summary.txt"
