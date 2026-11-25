#!/usr/bin/env bash
# Wait until Windows is quiet before starting simulation work, e.g. after a boot:
# CPU utility < MAX_CPU % and thermal zone <= MAX_C on 3 checks in a row (about a minute).
#
#   bash evaluation/scripts/wait_for_settle.sh [MAX_CPU=30] [MAX_C=65] [TIMEOUT_S=1800]
#
# Exit 0 when settled, 1 on timeout. Each check is logged to evaluation/progress/live.log.
# Used since 2026-11-24: right after a boot, Windows updates, Defender and VS Code kept the
# CPU near 100 % and the laptop at up to 83 C for several minutes.
cd "$(dirname "$0")/../.."
MAX_CPU=${1:-30}; MAX_C=${2:-65}; TIMEOUT=${3:-1800}
LIVE=evaluation/progress/live.log; mkdir -p evaluation/progress
start=$(date +%s); ok=0
while :; do
  read -r cpu temp < <(powershell.exe -NoProfile -c "\$c=(Get-Counter '\Processor Information(_Total)\% Processor Utility' -SampleInterval 5 -MaxSamples 1).CounterSamples[0].CookedValue; \$z=(Get-Counter '\Thermal Zone Information(*)\Temperature').CounterSamples[0].CookedValue; [math]::Round(\$c,0).ToString() + ' ' + [math]::Round(\$z-273.15,1).ToString()" 2>/dev/null | tr -d '\r')
  el=$(( $(date +%s) - start ))
  if awk -v c="$cpu" -v t="$temp" -v mc="$MAX_CPU" -v mt="$MAX_C" 'BEGIN{exit !(c!="" && c<mc && t<=mt)}'; then ok=$((ok+1)); else ok=0; fi
  echo "$(date +%T) [settle] windows cpu ${cpu:-?} %, thermal ${temp:-?} C (calm checks in a row: $ok)" | tee -a "$LIVE"
  if [ $ok -ge 3 ]; then echo "$(date +%T) [settle] settled after ${el} s" | tee -a "$LIVE"; exit 0; fi
  if [ $el -ge "$TIMEOUT" ]; then echo "$(date +%T) [settle] NOT settled after ${el} s" | tee -a "$LIVE"; exit 1; fi
  sleep 15
done
