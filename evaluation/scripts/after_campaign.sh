#!/usr/bin/env bash
# Safety net: when a campaign (or any process) ends, save its results without waiting for anyone.
#
#   setsid nohup bash evaluation/scripts/after_campaign.sh <pid> &
#
# Requested 2026-11-24 ("before the limit is reached, make sure to push to GitHub and save the
# backup"): if the assistant session that normally does the wrap-up is unavailable, the new
# recordings still reach GitHub and D:\. Waits for <pid> to exit, then:
#   1. packs the recordings (archive_recordings.py; deterministic, unchanged archives untouched)
#   2. copies the live log into evidence/phase_c/
#   3. commits only those files on the current branch (never main) and pushes it
#   4. mirrors the project to D:\ (backup_to_d.sh)
# The write-up of results is left for the assistant (it needs judgement); this only saves data.
cd "$(dirname "$0")/../.."
PID=$1
LIVE=evaluation/progress/live.log
log() { echo "$(date +%T) [autosave] $*" >> "$LIVE"; }

[ -n "$PID" ] && while kill -0 "$PID" 2>/dev/null; do sleep 20; done
log "process $PID ended: archiving recordings, committing, pushing, backing up"
# the same lock as periodic_save.sh (2026-11-25), so the two never commit at the same time
exec 9> evaluation/progress/.save.lock
flock 9

branch=$(git branch --show-current)
if [ "$branch" = "main" ] || [ -z "$branch" ]; then
    log "on '$branch': not committing automatically (only work branches); backup only"
else
    nice -n 19 python3 evaluation/scripts/archive_recordings.py >> "$LIVE" 2>&1
    cp "$LIVE" "evidence/phase_c/live_log_to_$(date +%F).txt"
    git add evaluation/recordings "evidence/phase_c/live_log_to_$(date +%F).txt"
    if git diff --cached --quiet; then
        log "nothing new to commit"
    else
        git commit -q -m "Auto-save after campaign ($(date '+%F %T')): recordings archived, live log copied

Saved by evaluation/scripts/after_campaign.sh; results write-up to follow.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && log "committed $(git rev-parse --short HEAD)"
        if GIT_TERMINAL_PROMPT=0 git push -q origin "$branch" 2>/dev/null; then
            log "pushed $branch $(git rev-parse --short HEAD)"
        else
            log "PUSH FAILED (credentials or network); commit is local"
        fi
    fi
fi
# wait for a mirror already running (e.g. started by the post-commit hook), then make the final one;
# without the wait, backup_to_d.sh returned at once ("already running") and this logged "done" early
flock -w 900 /tmp/yoru_backup_to_d.lock true
bash evaluation/scripts/backup_to_d.sh > /dev/null 2>&1 && log "D:\\ backup done" || log "D:\\ BACKUP FAILED"
