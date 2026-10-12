#!/usr/bin/env bash
# Health check for a running baseline batch, every INTERVAL seconds (default 600).
# Appends one line per check to evaluation/data/batch_watchdog.log and EXITS on the
# first problem (exit 1, with the reason) or when the batch has finished (exit 0),
# so whoever started it in the background is notified at once.
#   bash evaluation/scripts/watchdog.sh [interval_s]
# Problems: runner gone before 300 valid runs; no run finished for two checks;
# the last 3 runs all failed; more than one Gazebo server of this project;
# less than 5 GB free disk. A missing sleep/lid-switch block is restored.
set -uo pipefail
cd "$(dirname "$0")/../.."
INTERVAL="${1:-600}"
LOG=evaluation/data/batch_watchdog.log
BATCH_LOG=evaluation/data/baseline_batch.log
last_count=-1
stalled=0

valid_runs() {
    python3 - <<'EOF'
import csv
rows = {}
for r in csv.DictReader(open('evaluation/data/manifest.csv')):
    rows[r['run_id']] = r
print(sum(r['status'] == 'ok' for r in rows.values()))
EOF
}

problem() {
    echo "$(date '+%F %T') PROBLEM: $1" | tee -a "$LOG"
    exit 1
}

while true; do
    now=$(date '+%F %T')
    runner=$(pgrep -f "^python3 -u evaluation/scripts/run_batch.py" | head -1)
    valid=$(valid_runs)
    finished=$(grep -c "status=" "$BATCH_LOG")
    last3=$(grep -o "status=[a-z_]*" "$BATCH_LOG" | tail -3 | sort -u | tr '\n' ' ')
    gazebo=$(pgrep -f "^(sh -c )?gzserver .*(eval_two_room|two_room_world)\.world" | wc -l)
    free_gb=$(df -BG --output=avail . | tail -1 | tr -dc '0-9')
    position=$(grep -o "[0-9]*/300" "$BATCH_LOG" | tail -1)
    echo "$now valid=$valid/300 at=$position finished_this_session=$finished last3=[${last3% }] gazebo=$gazebo free=${free_gb}G runner=${runner:-none}" >> "$LOG"

    if [ -z "$runner" ]; then
        if [ "$valid" -ge 300 ]; then
            echo "$now batch finished: $valid/300 valid" | tee -a "$LOG"
            exit 0
        fi
        problem "the batch runner is not running and only $valid/300 runs are valid"
    fi
    if [ "$finished" -eq "$last_count" ]; then
        stalled=$((stalled + 1))
        [ "$stalled" -ge 2 ] && problem "no run finished in the last $((stalled * INTERVAL / 60)) min (stuck at $position)"
    else
        stalled=0
    fi
    last_count=$finished
    ok_in_last3=$(grep -o "status=[a-z_]*" "$BATCH_LOG" | tail -3 | grep -c "status=ok")
    if [ "$finished" -ge 3 ] && [ "$ok_in_last3" -eq 0 ]; then
        problem "none of the last 3 runs succeeded (${last3% })"
    fi
    [ "$gazebo" -gt 1 ] && problem "$gazebo Gazebo servers of this project are running (one escaped cleanup)"
    [ "$free_gb" -lt 5 ] && problem "only ${free_gb} GB of disk left"
    if ! systemd-inhibit --list 2>/dev/null | grep -q "Yoru evaluation"; then
        watcher=$(pgrep -f "^bash evaluation/scripts/after_batch.sh" | head -1)
        if [ -n "$watcher" ]; then
            setsid nohup systemd-inhibit --what=sleep:handle-lid-switch --who="Yoru evaluation batch" \
                --why="simulation batch and results pipeline in progress" --mode=block \
                bash -c "while kill -0 $watcher 2>/dev/null; do sleep 60; done" > /dev/null 2>&1 < /dev/null &
            echo "$now sleep block was missing: restored" >> "$LOG"
        fi
    fi
    sleep "$INTERVAL"
done
