#!/usr/bin/env bash
# Wait for a running batch (by PID) to exit, then build every Phase 5-6 result.
#   setsid nohup bash evaluation/scripts/after_batch.sh <runner_pid> > evaluation/data/after_batch.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/../.."
PID="$1"
echo "[after_batch] $(date -Is) waiting for batch pid $PID"
while kill -0 "$PID" 2>/dev/null; do sleep 60; done
echo "[after_batch] $(date -Is) batch finished; tail of its log:"
tail -3 evaluation/data/baseline_batch.log
# Only the results pipeline: nothing under src/ is touched.
nice -n 5 bash evaluation/scripts/make_results.sh
echo "[after_batch] $(date -Is) exit code $?"
