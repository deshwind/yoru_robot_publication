#!/usr/bin/env bash
# A day's campaign: up to N turbo-off gentle sessions with rests in between.
#
#   setsid nohup bash evaluation/scripts/run_campaign.sh <sessions> <rest_min> <gentle_batch args...> &
#   e.g. run_campaign.sh 3 30 --scenarios all --seed-list 3,4,...,19 --tag baseline_wsl \
#            --out evaluation/data/baseline_wsl --manifest evaluation/data/baseline_wsl/manifest.csv
#
# Decided 2026-11-24 for the laptop (it already lost an SSD slot): three one-hour sessions a day
# with 30-minute rests, turbo off (run_session_turbo_off.sh: boost mode restored after each
# session), temperature-aware cool-downs and thermal/throttling/failure stops inside each session.
# The campaign goes on to the next session only if the previous one ended because its time
# budget was used; any other ending (thermal limit, throttling, failures, STOP file) ends the
# campaign, and so does finishing every planned run. A STOP file during a rest ends it too.
cd "$(dirname "$0")/../.."
SESSIONS=${1:-3}; REST_MIN=${2:-30}; shift 2
LIVE=evaluation/progress/live.log
STOP=evaluation/progress/STOP
mkdir -p evaluation/progress
log() { echo "$(date +%T) [campaign] $*" >> "$LIVE"; }

to_do() {   # runs still to do for these gentle arguments
    source /opt/ros/humble/setup.bash >/dev/null 2>&1
    python3 evaluation/scripts/gentle_batch.py "$@" --dry-run 2>/dev/null \
        | head -1 | grep -o '[0-9]* to do' | grep -o '^[0-9]*'
}

log "start: up to $SESSIONS sessions, $REST_MIN min rest between them; args: $*"
for i in $(seq 1 "$SESSIONS"); do
    left=$(to_do "$@")
    if [ "${left:-1}" = "0" ]; then log "all planned runs done before session $i"; break; fi
    if [ -e "$STOP" ]; then log "STOP file present: campaign ended before session $i"; break; fi
    log "session $i/$SESSIONS: $left runs to do"
    bash evaluation/scripts/run_session_turbo_off.sh "$@"
    ending=$(grep '\[gentle\] session end' "$LIVE" | tail -1)
    case "$ending" in
        *"all planned runs done"*) log "all planned runs done"; break ;;
        *"time budget used"*) ;;
        *) log "campaign ended: last session stopped for another reason (${ending#*reason: })"; break ;;
    esac
    [ "$i" -ge "$SESSIONS" ] && { log "daily session limit reached ($SESSIONS)"; break; }
    log "rest $REST_MIN min (laptop idle)"
    for _ in $(seq 1 $((REST_MIN * 2))); do
        [ -e "$STOP" ] && break
        sleep 30
    done
    if [ -e "$STOP" ]; then log "STOP file present during the rest: campaign ended"; break; fi
done
log "end: $(to_do "$@") runs still to do"
