#!/usr/bin/env bash
# Start another campaign once the current one has ended and been saved, after a rest.
#
#   setsid bash evaluation/scripts/chain_campaign.sh <campaign pid> <rest_min> <start_campaign.sh args...> &
#
# Added 2026-11-25 when the user chose to run the baseline re-run overnight: tonight's 2-session
# campaign is followed, after its final save and a 30-minute rest, by a 5-session campaign
# (1-hour sessions, 30-minute rests), with the same safety net and 30-minute saves
# (SAVE_EVERY_MIN, passed through to start_campaign.sh). A STOP file at any point cancels it.
cd "$(dirname "$0")/../.."
PID=$1; REST=$2; shift 2
LIVE=evaluation/progress/live.log
STOP=evaluation/progress/STOP
log() { echo "$(date +%T) [chain] $*" >> "$LIVE"; }
stopped() { [ -e "$STOP" ] && { log "STOP file present: next campaign cancelled"; exit 0; }; }
log "waiting for campaign $PID and its final save; then $REST min rest, settle check, start_campaign.sh $*"
while kill -0 "$PID" 2>/dev/null; do sleep 20; done
while ps -eo args= | awk -v p="$PID" '$0 ~ "after_campaign.sh " p "$" {f=1} END {exit !f}'; do sleep 10; done
stopped
log "campaign $PID ended and saved; resting $REST min"
for ((i = 0; i < REST * 3; i++)); do stopped; sleep 20; done
stopped
if ! bash evaluation/scripts/wait_for_settle.sh 30 65 1800 > /dev/null; then
    log "Windows did not settle within 30 min: next campaign NOT started"; exit 1
fi
stopped
SAVE_EVERY_MIN=${SAVE_EVERY_MIN:-30} bash evaluation/scripts/start_campaign.sh "$@" >> "$LIVE" 2>&1
