#!/usr/bin/env bash
# Start a detached campaign and arm the safety net on the campaign's own process.
#
#   bash evaluation/scripts/start_campaign.sh <run_campaign.sh args...>
#   e.g. start_campaign.sh 2 30 --scenarios all --seed-list 3,4,...,19 --tag baseline_wsl \
#            --out evaluation/data/baseline_wsl --manifest evaluation/data/baseline_wsl/manifest.csv
#
# Why this exists (2026-11-25): `setsid nohup cmd &` forks when the shell runs it as a
# process-group leader, so `$!` was the pid of the setsid launcher, which exits at once.
# after_campaign.sh, armed with that pid, then archived, committed and pushed immediately,
# alongside a running simulation. Here the campaign writes its own pid ($$ survives exec).
cd "$(dirname "$0")/../.."
mkdir -p evaluation/progress
PIDFILE=evaluation/progress/campaign.pid
rm -f "$PIDFILE"
setsid bash -c 'echo $$ > evaluation/progress/campaign.pid; exec bash evaluation/scripts/run_campaign.sh "$@"' \
    campaign "$@" > evaluation/progress/campaign.out 2>&1 < /dev/null &
for _ in $(seq 100); do [ -s "$PIDFILE" ] && break; sleep 0.1; done
PID=$(cat "$PIDFILE" 2>/dev/null)
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    echo "campaign did not start (see evaluation/progress/campaign.out)"; exit 1
fi
setsid bash -c 'exec bash evaluation/scripts/after_campaign.sh "$1"' safety "$PID" \
    > evaluation/progress/after_campaign.out 2>&1 < /dev/null &
sleep 1
echo "$(date +%T) [campaign] started as pid $PID; safety net armed on it" >> evaluation/progress/live.log
echo "campaign pid $PID; safety net armed"
# SAVE_EVERY_MIN=30 [SAVE_GROUP=baseline_wsl]: also save every N minutes during the campaign
if [ -n "$SAVE_EVERY_MIN" ]; then
    setsid bash -c 'exec bash evaluation/scripts/periodic_save.sh "$1" "$2" "$3"' save "$PID" \
        "$SAVE_EVERY_MIN" "${SAVE_GROUP:-baseline_wsl}" > /dev/null 2>&1 < /dev/null &
    echo "periodic save every $SAVE_EVERY_MIN min armed"
fi
