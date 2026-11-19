#!/usr/bin/env python3
"""Clock probe: detects VM stalls and wall-clock jumps, idle and under CPU load.

Samples the monotonic and the wall (realtime) clock every 50 ms for 20 s idle,
then for 20 s with N busy processes, and reports every interval where the
monotonic gap exceeds 0.5 s (the machine stalled) or the wall gap differs from
the monotonic gap by more than 0.5 s (the wall clock was stepped).

  python3 evaluation/scripts/clock_probe.py [N busy processes, default 14]

Used on 2026-11-19 to find the ±21.6 s wall-clock jumps on the replacement
machine (evidence/README.md, "Replacement machine").
"""

import multiprocessing as mp
import sys
import time


def burn(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pass


def watch(duration, label):
    stalls, last_m, last_r = [], time.monotonic(), time.time()
    end = last_m + duration
    while time.monotonic() < end:
        time.sleep(0.05)
        m, r = time.monotonic(), time.time()
        if m - last_m > 0.5 or abs((r - last_r) - (m - last_m)) > 0.5:
            stalls.append((round(m - last_m, 2), round(r - last_r, 2)))
        last_m, last_r = m, r
    print(f'{label}: {len(stalls)} stalls/jumps (monotonic gap, wall gap): {stalls[:10]}',
          flush=True)
    return len(stalls)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    bad = watch(20, 'idle')
    procs = [mp.Process(target=burn, args=(25,)) for _ in range(n)]
    for p in procs:
        p.start()
    bad += watch(20, f'load {n} procs')
    for p in procs:
        p.join()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
