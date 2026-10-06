#!/usr/bin/env bash
# Resume the baseline batch where it stopped, detached from the terminal:
# valid runs are skipped, failed or interrupted ones are redone (their old
# folders move to evaluation/data/runs_invalid/), and when the batch ends the
# full results pipeline (make_results.sh) runs automatically. Sleep and
# lid-close suspend are blocked until then.
#   bash evaluation/scripts/resume_baseline.sh
# Progress: grep -c 'status=ok' evaluation/data/baseline_batch.log
#           tail -1 evaluation/data/baseline_batch.log      (shows "<n>/300")
set -euo pipefail
cd "$(dirname "$0")/../.."
if pgrep -f "^python3 -u evaluation/scripts/run_batch.py" > /dev/null; then
    echo "a batch is already running"; exit 1
fi
[ -f evaluation/data/baseline_batch.log ] && \
    mv evaluation/data/baseline_batch.log "evaluation/data/baseline_batch_$(date +%Y%m%dT%H%M%S).log"
setsid nohup bash -c 'source /opt/ros/humble/setup.bash && source install/setup.bash && exec python3 -u evaluation/scripts/run_batch.py --scenarios all --seeds 20 --skip-existing' \
    > evaluation/data/baseline_batch.log 2>&1 < /dev/null &
sleep 3
RUNNER=$(pgrep -f "^python3 -u evaluation/scripts/run_batch.py" | head -1)
setsid nohup bash evaluation/scripts/after_batch.sh "$RUNNER" >> evaluation/data/after_batch.log 2>&1 < /dev/null &
sleep 1
WATCHER=$(pgrep -f "after_batch.sh $RUNNER" | head -1)
setsid nohup systemd-inhibit --what=sleep:handle-lid-switch --who="Yoru evaluation batch" \
    --why="simulation batch and results pipeline in progress" --mode=block \
    bash -c "while kill -0 $WATCHER 2>/dev/null; do sleep 60; done" > /dev/null 2>&1 < /dev/null &
echo "resumed: runner $RUNNER, results watcher $WATCHER"
