#!/usr/bin/env bash
# Mirror of the whole project on D:\ (a separate physical drive: Kingston SSD on USB).
#
#   bash evaluation/scripts/backup_to_d.sh            # usually called automatically
#
# Requested 2026-11-24: keep one always-up-to-date copy on D:\, replacing the old one each time.
# A mirror sync gives exactly that: changed files are copied, files gone from the project are
# deleted from the copy, and nothing else is kept. New files are put in place only at the end
# (--delay-updates) and deletions happen after the transfer (--delete-after), so an interrupted
# sync never leaves a half-updated copy. Includes the git history, the recordings and the live
# log; leaves out the colcon build outputs (build/, install/, log/), which can be rebuilt.
# Called by the git post-commit hook and at the end of every simulation session.
set -o pipefail
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
DEST=/mnt/d/yoru_backup
LOCK=/tmp/yoru_backup_to_d.lock
LIVE="$SRC/evaluation/progress/live.log"

[ -d /mnt/d ] || { echo "D: is not mounted: no backup" >&2; exit 1; }
mkdir -p "$DEST"
exec 9>"$LOCK"
if ! flock -n 9; then
    # Another backup is running. It may have started before the commit that called this one
    # (2026-11-27 21:41: the session-end mirror began 40 s before a periodic save's commit,
    # whose hook then skipped, so D:\ stayed one commit behind). Wait for it, then mirror again.
    waited_from=$(date +%s)
    if ! flock -w 900 9; then
        [ -d "$(dirname "$LIVE")" ] && echo "$(date +%T) [backup] D:\\ mirror FAILED (another backup still running after 15 min)" >> "$LIVE"
        exit 1
    fi
    [ -d "$(dirname "$LIVE")" ] && echo "$(date +%T) [backup] waited $(( $(date +%s) - waited_from )) s for the running backup; mirroring again so nothing committed during it is missed" >> "$LIVE"
fi

start=$(date +%s)
nice -n 19 ionice -c3 rsync -rt --modify-window=2 --delete-after --delay-updates \
    --exclude='/build/' --exclude='/install/' --exclude='/log/' \
    --exclude='__pycache__/' --exclude='*.pyc' \
    "$SRC/" "$DEST/yoru_robot_publication/"
status=$?
commit=$(git -C "$SRC" log -1 --format='%h %s' 2>/dev/null)
size=$(du -sh "$DEST/yoru_robot_publication" 2>/dev/null | cut -f1)
if [ $status -eq 0 ]; then
    printf 'Yoru project backup (mirror of %s)\nlast updated: %s\nbranch: %s\nlatest commit: %s\nsize: %s\n' \
        "$SRC" "$(date '+%F %T')" "$(git -C "$SRC" branch --show-current)" "$commit" "$size" \
        > "$DEST/BACKUP_INFO.txt"
    [ -d "$(dirname "$LIVE")" ] && echo "$(date +%T) [backup] D:\\ mirror updated in $(( $(date +%s) - start )) s ($size, $commit)" >> "$LIVE"
else
    [ -d "$(dirname "$LIVE")" ] && echo "$(date +%T) [backup] D:\\ mirror FAILED (rsync exit $status)" >> "$LIVE"
fi
exit $status
