#!/usr/bin/env bash
# One gentle Phase C session with the CPU's turbo boost disabled, restored on exit.
#
# Turbo off keeps this laptop's thermal zone at about 53-57 C during runs instead of
# about 85 C, with the same YOLO rate and outcomes (evidence/README.md, Phase C,
# 2026-11-23). Windows' 'maximum processor state' does not stop turbo on this CPU;
# the hidden 'processor performance boost mode' does (0 = Disabled). It is set back
# to 2 (Aggressive: this plan's DC value and Windows' default) when the session ends,
# however it ends. With turbo off the CPU reads ~79 % performance while busy, so the
# throttling threshold is 70 %.
#   setsid nohup bash evaluation/scripts/run_session_turbo_off.sh <gentle_batch args...> &
cd "$(dirname "$0")/../.."
LIVE=evaluation/progress/live.log
mkdir -p evaluation/progress
boost() {
    powershell.exe -NoProfile -c "powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE $1; powercfg /setactive SCHEME_CURRENT; (powercfg /qh SCHEME_CURRENT SUB_PROCESSOR PERFBOOSTMODE | Select-String 'Current AC').Line.Trim()" 2>/dev/null | tr -d '\r'
}
restore() {
    echo "$(date +%T) [turbo] restored: $(boost 2)" >> "$LIVE"
}
trap restore EXIT
echo "$(date +%T) [turbo] boost disabled for the session: $(boost 0)" >> "$LIVE"
bash evaluation/scripts/run_phase_c_session.sh --min-perf 70 --cool-to 65 --max-thermal 88 "$@"
