#!/usr/bin/env python3
"""Gentle batch: run_batch.py one run at a time, with the laptop's limits built in.

The laptop that runs the evaluation already lost an SSD slot, so batches are
kept short and supervised (decision of 2026-11-19):

  - one session lasts at most --max-minutes (default 60): no new run starts
    after that;
  - --cooldown-s (default 120) of idle time between runs;
  - the host monitor (host_monitor.sh) runs for the whole session, and the
    session stops if Windows reports the CPU throttled while a run was busy
    (median '% processor performance' below --min-perf, default 85; it is
    98-108 % in normal runs);
  - the session stops after --max-failures (default 2) failed runs in a row;
  - creating evaluation/progress/STOP stops it after the current run;
  - each session resumes where the last one stopped: runs already 'ok' in the
    manifest are skipped.

Each run is an ordinary run_batch.py run (same checks, retries, manifest row and
run directory), so gentle sessions and plain batches produce identical records.
Progress goes to evaluation/progress/live.log ([gentle] lines); run_batch.py's
own output is appended to <out>/batch.log.

  python3 evaluation/scripts/gentle_batch.py --scenarios H,C,A --seeds 10 \\
      --compliance-aware hold_s1 --out evaluation/data/variants \\
      --manifest evaluation/data/variants/manifest.csv
  touch evaluation/progress/STOP      # stop after the current run
"""

import argparse
import csv
import datetime
import fcntl
import os
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_batch as rb  # noqa: E402

PROGRESS = os.path.join(rb.EVAL, 'progress')
LIVE = os.path.join(PROGRESS, 'live.log')
MONITOR_LOG = os.path.join(PROGRESS, 'host_monitor.log')
STOP_FILE = os.path.join(PROGRESS, 'STOP')


# ------------------------------------------------------------ pure helpers

def run_tag(cli_tag, variant):
    """The run-set tag run_batch.py will use (no weight options here)."""
    if cli_tag:
        return cli_tag
    return variant['tag'] or 'baseline'


def pending_runs(plan, manifest, tag):
    """(scenario_id, seed) pairs of the plan not yet 'ok' in the manifest
    (latest row per run counts, as in run_batch --skip-existing)."""
    latest = {}
    if os.path.isfile(manifest):
        with open(manifest, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                latest[(r['tag'], r['scenario'], r['seed'])] = r['status']
    return [(s, seed) for s, seed in plan if latest.get((tag, s, str(seed))) != 'ok']


def last_row(manifest, run_id):
    if not os.path.isfile(manifest):
        return None
    row = None
    with open(manifest, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['run_id'] == run_id:
                row = r
    return row


def current_monitor_lines(path):
    """Lines written by the most recent host monitor: those after the last '# time'
    header. The log keeps earlier days' lines and stores times only (no dates), so a
    time window alone would also match another day's lines (found 2026-11-24: A/7-A/9
    of reset_first were reported with 23 Nov's turbo-on readings)."""
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    last_header = max((i for i, l in enumerate(lines) if l.startswith('# time')), default=-1)
    return lines[last_header + 1:]


def monitor_samples(path, start, end):
    """(time, performance %, utility %) samples of host_monitor.log taken
    between two datetimes of the same day (the log has times only)."""
    samples = []
    if not os.path.isfile(path):
        return samples
    for line in current_monitor_lines(path):
        parts = [p.strip() for p in line.split('|')]
        if line.startswith('#') or len(parts) < 3:
            continue
        try:
            t = datetime.datetime.combine(start.date(),
                                          datetime.time.fromisoformat(parts[0]))
            perf, util = float(parts[1]), float(parts[2])
        except ValueError:
            continue
        if start <= t <= end:
            samples.append((t, perf, util))
    return samples


def throttled(samples, min_perf, busy_util=40.0, min_busy=2):
    """True if the CPU ran below min_perf % of its nominal performance while
    busy (utility >= busy_util): median over the busy samples, at least
    min_busy of them. Idle samples are ignored (low performance is normal
    when idle)."""
    busy = [perf for _, perf, util in samples if util >= busy_util]
    if len(busy) < min_busy:
        return False, None
    median = statistics.median(busy)
    return median < min_perf, median


def thermal_readings(path, start, end):
    """(time, thermal zone deg C) readings of host_monitor.log between two
    datetimes of the same day. Lines without the thermal column (monitor
    versions before 2026-11-19 16:41) are skipped."""
    readings = []
    if not os.path.isfile(path):
        return readings
    for line in current_monitor_lines(path):
        parts = [p.strip() for p in line.split('|')]
        if line.startswith('#') or len(parts) < 9:
            continue
        try:
            t = datetime.datetime.combine(start.date(),
                                          datetime.time.fromisoformat(parts[0]))
            value = float(parts[7])
        except ValueError:
            continue
        if start <= t <= end:
            readings.append((t, value))
    return readings


# Locks held by a save in progress (periodic_save.sh / after_campaign.sh) and by the D:\ mirror
# (backup_to_d.sh, started by the post-commit hook). Added 2026-11-26: on the overnight run a
# 25-53 s mirror sometimes ran into the start of the next run.
SAVE_LOCKS = [os.path.join(PROGRESS, '.save.lock'), '/tmp/yoru_backup_to_d.lock']


def wait_for_saves(lock_paths=None, max_wait_s=300.0, poll_s=2.0):
    """Wait until no save or backup holds one of the lock files (flock), at most max_wait_s.
    Returns the seconds waited. A missing lock file means nothing holds it."""
    start = time.monotonic()
    for path in (SAVE_LOCKS if lock_paths is None else lock_paths):
        while os.path.exists(path):
            with open(path, 'a') as f:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(f, fcntl.LOCK_UN)
                    break
                except OSError:
                    pass
            if time.monotonic() - start >= max_wait_s:
                break
            time.sleep(poll_s)
    waited = time.monotonic() - start
    return waited


def cooled(readings_after, cool_to):
    """True when the latest thermal reading taken after the run is at or below
    cool_to; False when it is above; None when there is no such reading yet."""
    if not readings_after:
        return None
    return readings_after[-1][1] <= cool_to


def stop_reason(*, elapsed_min, max_minutes, failures, max_failures, throttle,
                stop_file_present, thermal_peak=None, max_thermal=None):
    """Why the session must stop before the next run, or None to continue."""
    if stop_file_present:
        return 'STOP file present (manual stop)'
    if thermal_peak is not None and max_thermal is not None and thermal_peak > max_thermal:
        return f'thermal zone reached {thermal_peak:.1f} C (limit {max_thermal:g} C)'
    if throttle:
        return 'CPU throttling reported by Windows while a run was busy'
    if failures >= max_failures:
        return f'{failures} failed runs in a row'
    if elapsed_min >= max_minutes:
        return f'session time budget used ({max_minutes:g} min)'
    return None


def domain_offset(session_start, run_index):
    """Offset for run_batch --domain-offset: consecutive runs of a session get consecutive
    offsets (so different domains), and the start point moves with the clock so that the
    next session does not begin on the domain the previous one ended on."""
    return (int(session_start.timestamp()) // 60 + run_index) % 40


def clean_fastdds_shm():
    """Remove Fast DDS shared-memory segments and ports no live process holds
    ('fastdds shm clean' only touches zombie files). Best effort."""
    try:
        subprocess.run(['fastdds', 'shm', 'clean'], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


# ------------------------------------------------------------ the session

def live(message):
    os.makedirs(PROGRESS, exist_ok=True)
    with open(LIVE, 'a', encoding='utf-8') as f:
        f.write(f'{datetime.datetime.now():%H:%M:%S} [gentle] {message}\n')
    print(f'[gentle] {message}', flush=True)


def run_plan(scenario_ids, seeds, order='scenario'):
    """(scenario, seed) pairs in run order. 'seed' order (added 2026-11-25 for the
    255-run baseline re-run, about six days): each seed's scenarios run together, so
    every finished day adds complete seeds, and heavy and light scenarios alternate."""
    if order == 'seed':
        return [(sid, seed) for seed in seeds for sid in scenario_ids]
    if order == 'scenario':
        return [(sid, seed) for sid in scenario_ids for seed in seeds]
    raise ValueError(f'unknown order {order!r}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--scenarios', default='all')
    ap.add_argument('--seeds', type=int, default=10, help='seeds 0..N-1')
    ap.add_argument('--seed-list')
    ap.add_argument('--order', choices=('scenario', 'seed'), default='scenario',
                    help="'scenario' (default): every seed of a scenario, then the next "
                         "scenario; 'seed': every scenario of a seed, then the next seed, so "
                         "that a partly done set is still balanced across scenarios")
    ap.add_argument('--skip-pa', action='store_true')
    ap.add_argument('--sustained-ratio', type=float, default=0.0)
    ap.add_argument('--compliance-aware', choices=('hold_s1', 'reset_first', 'both'), default='')
    ap.add_argument('--tag')
    ap.add_argument('--out', required=True)
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--max-minutes', type=float, default=60.0)
    ap.add_argument('--cooldown-s', type=float, default=120.0)
    ap.add_argument('--min-perf', type=float, default=85.0)
    ap.add_argument('--max-failures', type=int, default=2)
    ap.add_argument('--cool-to', type=float, default=65.0,
                    help='after the fixed cool-down, also wait until the Windows thermal zone '
                         'is at or below this (deg C); 0 = time only')
    ap.add_argument('--max-cool-wait', type=float, default=600.0,
                    help='longest extra wait for --cool-to (s); then the session stops')
    ap.add_argument('--max-thermal', type=float, default=88.0,
                    help='stop the session if the thermal zone exceeded this during a run (deg C)')
    ap.add_argument('--dry-run', action='store_true')
    cli = ap.parse_args()

    try:
        variant = rb.variant_settings(cli.skip_pa, cli.sustained_ratio, cli.compliance_aware)
        rb.manifest_fieldnames(os.path.abspath(cli.manifest), variant['tag'])
    except ValueError as exc:
        sys.exit(f'[gentle] {exc}')
    tag = run_tag(cli.tag, variant)
    seeds = ([int(s) for s in cli.seed_list.split(',')] if cli.seed_list
             else list(range(cli.seeds)))
    plan = run_plan([s['id'] for s in rb.load_scenarios(cli.scenarios)], seeds, cli.order)
    todo = pending_runs(plan, cli.manifest, tag)
    print(f'[gentle] tag={tag}: {len(plan)} runs planned, {len(plan) - len(todo)} already ok, '
          f'{len(todo)} to do; session <= {cli.max_minutes:g} min, cool-down {cli.cooldown_s:g} s')
    if cli.dry_run or not todo:
        for s, seed in todo:
            print(f'  {s:8s} seed {seed}')
        return 0
    if os.path.exists(STOP_FILE):
        sys.exit(f'[gentle] {STOP_FILE} exists: remove it to start a session')

    passthrough = []
    if cli.skip_pa:
        passthrough.append('--skip-pa')
    if cli.sustained_ratio:
        passthrough += ['--sustained-ratio', str(cli.sustained_ratio)]
    if cli.compliance_aware:
        passthrough += ['--compliance-aware', cli.compliance_aware]
    if cli.tag:
        passthrough += ['--tag', cli.tag]

    monitor = subprocess.Popen(
        ['bash', os.path.join(rb.EVAL, 'scripts', 'host_monitor.sh'), str(os.getpid()), '60'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    session_start = datetime.datetime.now()
    live(f'session start: tag={tag}, {len(todo)} of {len(plan)} runs to do; '
         f'budget {cli.max_minutes:g} min, cool-down {cli.cooldown_s:g} s, '
         f'stop if CPU performance < {cli.min_perf:g} % while busy')
    done = failures = 0
    reason = None
    try:
        for i, (scenario, seed) in enumerate(todo):
            held = wait_for_saves()
            if held >= 1.0:
                live(f'  waited {held:.0f} s for a save/backup to finish before the run')
            run_start = datetime.datetime.now()
            live(f'run {i + 1}/{len(todo)}: {scenario} seed {seed}')
            # A fresh DDS domain for every run (rotating through 60-99, as a plain batch
            # does) and no stale Fast DDS shared memory: reusing domain 61 run after run
            # went with 3-4x more nav2_not_ready failures (2026-11-24)
            clean_fastdds_shm()
            cmd = [sys.executable, '-u', os.path.join(rb.EVAL, 'scripts', 'run_batch.py'),
                   '--scenarios', scenario, '--seed-list', str(seed), '--skip-existing',
                   '--out', cli.out, '--manifest', cli.manifest,
                   '--domain-offset', str(domain_offset(session_start, i)), *passthrough]
            os.makedirs(cli.out, exist_ok=True)
            with open(os.path.join(cli.out, 'batch.log'), 'a', encoding='utf-8') as log:
                subprocess.run(cmd, cwd=rb.ROOT, check=False, stdout=log,
                               stderr=subprocess.STDOUT)
            row = last_row(cli.manifest, f'{tag}/{scenario}/{seed}')
            status = row['status'] if row else 'no_manifest_row'
            if status == 'ok':
                done += 1
                failures = 0
                live(f'  ok: {row["outcome"]} {row["outcome_stage"]} at {row["outcome_sim_t"]} s sim, '
                     f'RTF {row["rtf"]}')
            else:
                failures += 1
                live(f'  NOT ok: {status} ({failures} in a row)')
            samples = monitor_samples(MONITOR_LOG, run_start, datetime.datetime.now())
            is_throttled, median_perf = throttled(samples, cli.min_perf)
            if median_perf is not None:
                live(f'  CPU performance while busy: median {median_perf:.0f} % '
                     f'({len(samples)} monitor samples)')
            run_end = datetime.datetime.now()
            temps = thermal_readings(MONITOR_LOG, run_start, run_end)
            peak = max((v for _, v in temps), default=None)
            if peak is not None:
                live(f'  thermal zone during the run: peak {peak:.1f} C')
            elapsed = (run_end - session_start).total_seconds() / 60.0
            reason = stop_reason(elapsed_min=elapsed, max_minutes=cli.max_minutes,
                                 failures=failures, max_failures=cli.max_failures,
                                 throttle=is_throttled,
                                 stop_file_present=os.path.exists(STOP_FILE),
                                 thermal_peak=peak, max_thermal=cli.max_thermal)
            if reason or i == len(todo) - 1:
                break
            live(f'  cool-down {cli.cooldown_s:g} s')
            time.sleep(cli.cooldown_s)
            if os.path.exists(STOP_FILE):
                reason = 'STOP file present (manual stop)'
                break
            # Temperature-aware cool-down (user, 2026-11-23: "don't overpush it"):
            # keep waiting until a reading taken after the run is <= cool_to
            if cli.cool_to > 0:
                waited = 0.0
                while True:
                    state = cooled(thermal_readings(MONITOR_LOG, run_end,
                                                    datetime.datetime.now()), cli.cool_to)
                    if state is None and waited == 0.0 and not temps:
                        live('  no thermal readings (older monitor?): time-only cool-down')
                        break
                    if state:
                        if waited:
                            live(f'  cooled to <= {cli.cool_to:g} C after {waited:.0f} s extra')
                        break
                    if waited >= cli.max_cool_wait:
                        reason = (f'thermal zone still above {cli.cool_to:g} C after '
                                  f'{cli.max_cool_wait:g} s extra cool-down')
                        break
                    if waited == 0.0:
                        live(f'  still warm: waiting until the thermal zone is <= {cli.cool_to:g} C'
                             if state is False else
                             '  no thermal reading since the run yet (the monitor samples about once '
                             'a minute): waiting for one')
                    time.sleep(30)
                    waited += 30
                    if os.path.exists(STOP_FILE):
                        reason = 'STOP file present (manual stop)'
                        break
                if reason:
                    break
    except KeyboardInterrupt:
        reason = 'interrupted (Ctrl+C)'
    finally:
        monitor.terminate()
    remaining = len(pending_runs(plan, cli.manifest, tag))
    minutes = (datetime.datetime.now() - session_start).total_seconds() / 60.0
    live(f'session end after {minutes:.0f} min: {done} run(s) ok this session; {remaining} of '
         f'{len(plan)} still to do; reason: {reason or "all planned runs done"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
