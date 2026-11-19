#!/usr/bin/env bash
# Host-side monitor for runs under WSL: every INTERVAL s (default 60), logs the Windows CPU
# performance level (100 % = nominal clock; lower = throttled), CPU utility, the three busiest
# Windows processes, and the Linux side's load, free memory and Fast DDS /dev/shm file count.
# Stops when the process PID (e.g. the batch runner) exits.
#   bash evaluation/scripts/host_monitor.sh <pid> [interval_s]
cd "$(dirname "$0")/../.."
PID=$1; INTERVAL=${2:-60}
LOG=evaluation/progress/host_monitor.log
mkdir -p evaluation/progress
echo "# time | win_cpu_performance% | win_cpu_utility% | top Windows processes (% of one core) | linux load | mem_avail_MB | shm_files" >> "$LOG"
while kill -0 "$PID" 2>/dev/null; do
    win=$(powershell.exe -NoProfile -c "
      \$c = Get-Counter '\Processor Information(_Total)\% Processor Performance','\Processor Information(_Total)\% Processor Utility' -SampleInterval 2 -MaxSamples 1;
      \$p = \$c.CounterSamples[0].CookedValue.ToString('0'); \$u = \$c.CounterSamples[1].CookedValue.ToString('0');
      \$t = (Get-Counter '\Process(*)\% Processor Time' -SampleInterval 2 -MaxSamples 1).CounterSamples |
            Where-Object { \$_.InstanceName -notin @('_total','idle') } | Sort-Object CookedValue -Descending |
            Select-Object -First 3 | ForEach-Object { \$_.InstanceName + '=' + \$_.CookedValue.ToString('0') };
      \$p + ' | ' + \$u + ' | ' + (\$t -join ' ')" 2>/dev/null | tr -d '\r')
    echo "$(date +%T) | $win | $(cut -d' ' -f1 /proc/loadavg) | $(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) | $(ls /dev/shm | wc -l)" >> "$LOG"
    sleep "$INTERVAL"
done
echo "$(date +%T) monitored process $PID exited; monitor stopped" >> "$LOG"
