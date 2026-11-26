#!/usr/bin/env bash
# Periodic save while a campaign runs: every N minutes, archive a run set's recordings, commit
# them on the work branch, push to GitHub and mirror the project to D:\.
#
#   setsid bash evaluation/scripts/periodic_save.sh <campaign pid> [minutes=30] [group=baseline_wsl] &
#
# Requested 2026-11-25 for the overnight baseline re-run: "every 30 mins push to GitHub and the
# backup ... so it is safe". Each save waits for a gap between runs (cool-down or rest), so it never
# overlaps a simulation, and repacks only the given group (archive_recordings.py --only, ~2 s).
# Shares a lock with after_campaign.sh, which makes the final save when the campaign ends.
cd "$(dirname "$0")/../.."
PID=$1; MIN=${2:-30}; GROUP=${3:-baseline_wsl}
LIVE=evaluation/progress/live.log
LOCK=evaluation/progress/.save.lock
log() { echo "$(date +%T) [save] $*" >> "$LIVE"; }
alive() { kill -0 "$PID" 2>/dev/null; }
in_gap() {   # the last session line is not a run start: cool-down, rest or between sessions
    local last
    last=$(grep -E '\[(gentle|campaign)\]' "$LIVE" | tail -1)
    ! grep -qE '\[gentle\] run [0-9]+/[0-9]+:' <<< "$last"
}

[ -n "$PID" ] || { echo "usage: periodic_save.sh <campaign pid> [minutes] [group]"; exit 2; }
log "every $MIN min while process $PID runs: archive '$GROUP', commit, push, back up (in gaps between runs)"
while alive; do
    for ((i = 0; i < MIN * 3; i++)); do alive || break 2; sleep 20; done
    for ((i = 0; i < 180; i++)); do in_gap && break; alive || break 2; sleep 5; done
    (
        flock 9
        branch=$(git branch --show-current)
        if [ "$branch" = "main" ] || [ -z "$branch" ]; then
            log "on '$branch': not committing (only work branches)"
            bash evaluation/scripts/backup_to_d.sh > /dev/null 2>&1 && log "D:\\ backup done" || log "D:\\ BACKUP FAILED"
            exit 0
        fi
        nice -n 19 python3 evaluation/scripts/archive_recordings.py --only "$GROUP" >> "$LIVE" 2>&1
        git add evaluation/recordings
        if git diff --cached --quiet; then
            # nothing new since the last save, which already mirrored to D:\ (post-commit hook).
            # No backup here (2026-11-26): the save that ends a 30-min rest found nothing new, and
            # its 25-50 s mirror overlapped the start-up of the next session's first run.
            log "no new recordings since the last save; backup skipped (D:\\ already has them)"
        else
            runs=$(awk -F, 'NR > 1 && $12 == "ok"' "evaluation/recordings/$GROUP/manifest.csv" 2>/dev/null | wc -l)
            git commit -q -m "Periodic save ($(date '+%F %H:%M')): $GROUP recordings, $runs valid runs so far

Saved by evaluation/scripts/periodic_save.sh during the campaign.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && log "committed $(git rev-parse --short HEAD) ($runs valid runs)"
            if GIT_TERMINAL_PROMPT=0 git push -q origin "$branch" 2>/dev/null; then
                log "pushed $branch $(git rev-parse --short HEAD)"
            else
                log "PUSH FAILED (credentials or network); commit is local"
            fi
            # the post-commit hook mirrors to D:\ (logged as a [backup] line)
        fi
    ) 9> "$LOCK"
    [ "${ONCE:-0}" = 1 ] && break   # ONCE=1: one save, then exit (for a test or a save on demand)
done
log "process $PID ended; periodic saves stop (after_campaign.sh makes the final save)"
