#!/usr/bin/env python3
"""Batch runner: scenarios x seeds in headless Gazebo, one rosbag2 per run.

Each run:
  1. merges evaluation/config/eval_base.yaml + evaluation/scenarios/<id>.yaml
     + per-run values (seed, scenario_id, incident log dir) into
     <run_dir>/overlay.yaml
  2. launches sim_full.launch.py headless (gzserver only) in its own process
     group, on its own ROS_DOMAIN_ID, recording <run_dir>/bag
  3. watches /clock and /compliance/fsm_state; stops post_outcome_s (sim)
     after the escalation outcome, or at max_sim_s for runs that never
     escalate, or at the wall-clock timeout
  4. stops the whole process group (SIGINT -> SIGTERM -> SIGKILL) and checks
     that nothing from the run survived
  5. appends a row to the manifest CSV and writes <run_dir>/run_info.json

Run directories: <out>/<tag>/<scenario>/<seed>/ (tag = 'baseline' or the
weight/threshold setting). Requires ROS 2 and this workspace to be sourced:

  source /opt/ros/humble/setup.bash && source install/setup.bash
  python3 evaluation/scripts/run_batch.py --scenarios A --seeds 3          # pilot
  python3 evaluation/scripts/run_batch.py --scenarios all --seeds 20       # full
  python3 evaluation/scripts/run_batch.py --scenarios A,G --seeds 20 \\
      --w-d 0.5 --w-p 0.25 --w-t 0.15 --w-s 0.10 --threshold 0.6
"""

import argparse
import copy
import csv
import datetime
import glob
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVAL = os.path.join(ROOT, 'evaluation')
OUTCOMES = ('complied', 'target_lost', 'admin_override', 'logged_no_compliance',
            'safety_stop')
MANIFEST_FIELDS = [
    'run_id', 'tag', 'scenario', 'seed', 'w_D', 'w_P', 'w_T', 'w_S',
    'confirm_confidence', 'uncertain_confidence', 'ablation', 'status', 'outcome',
    'outcome_stage', 'outcome_sim_t', 'expected_outcome', 'ground_truth',
    'start_wall', 'end_wall', 'wall_s', 'sim_s', 'rtf', 'attempts', 'bag_ok',
    'died_processes', 'code_sha256', 'run_dir']


# ------------------------------------------------------------------ config

def deep_merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_scenarios(selection):
    files = sorted(glob.glob(os.path.join(EVAL, 'scenarios', '*.yaml')))
    scenarios = {}
    for path in files:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
        scenarios[data['id']] = data
    if selection == 'all':
        return [scenarios[k] for k in sorted(scenarios)]
    missing = [s for s in selection.split(',') if s not in scenarios]
    if missing:
        sys.exit(f'unknown scenario(s): {missing}; available: {sorted(scenarios)}')
    return [scenarios[s] for s in selection.split(',')]


def build_overlay(scenario, seed, run_dir):
    with open(os.path.join(EVAL, 'config', 'eval_base.yaml'), encoding='utf-8') as f:
        overlay = yaml.safe_load(f)
    scenario_params = {node: {'ros__parameters': params}
                       for node, params in scenario['params'].items()}
    overlay = deep_merge(overlay, scenario_params)
    per_run = {
        'scenario_publisher_node': {'ros__parameters': {
            'seed': seed, 'scenario_id': f'{scenario["id"]}_s{seed}'}},
        'human_actor_node': {'ros__parameters': {'seed': seed}},
        'incident_logger_node': {'ros__parameters': {
            'log_dir': os.path.join(run_dir, 'incident_logs')}},
    }
    return deep_merge(overlay, per_run)


def launch_args(weights, ablation=None):
    with open(os.path.join(EVAL, 'config', 'eval_launch.yaml'), encoding='utf-8') as f:
        args = yaml.safe_load(f)
    world = args.pop('world')
    args['world'] = os.path.join(ROOT, 'install', 'yoru_bringup', 'share',
                                 'yoru_bringup', 'worlds', world)
    args.update({k: v for k, v in weights.items() if v is not None})
    if ablation:
        args[f'ablate_{ablation}'] = 'true'
    return [f'{k}:={str(v).lower() if isinstance(v, bool) else v}'
            for k, v in args.items()]


def weight_settings(cli):
    w = {'w_D': cli.w_d, 'w_P': cli.w_p, 'w_T': cli.w_t, 'w_S': cli.w_s,
         'confirm_confidence': cli.threshold,
         'uncertain_confidence': (round(cli.threshold - 0.20, 6)
                                  if cli.threshold is not None else None)}
    if cli.tag:
        tag = cli.tag
    elif all(v is None for v in w.values()):
        tag = 'baseline'
    else:
        tag = '_'.join(f'{k}{v:g}' for k, v in w.items()
                       if v is not None and k != 'uncertain_confidence')
    return w, tag


def code_fingerprint():
    """SHA-256 over the source tree, so every run records the exact code."""
    digest = hashlib.sha256()
    for path in sorted(glob.glob(os.path.join(ROOT, 'src', '**', '*'), recursive=True)):
        if os.path.isfile(path) and '__pycache__' not in path:
            digest.update(os.path.relpath(path, ROOT).encode())
            with open(path, 'rb') as f:
                digest.update(f.read())
    for path in sorted(glob.glob(os.path.join(EVAL, 'config', '*.yaml'))
                       + glob.glob(os.path.join(EVAL, 'scenarios', '*.yaml'))):
        with open(path, 'rb') as f:
            digest.update(f.read())
    return digest.hexdigest()[:16]


# ----------------------------------------------------------------- monitor

class RunMonitor:
    """Watches /clock and /compliance/fsm_state on the run's DDS domain."""

    def __init__(self, domain_id):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rosgraph_msgs.msg import Clock
        from std_msgs.msg import String

        self.rclpy = rclpy
        self.context = rclpy.Context()
        rclpy.init(context=self.context, domain_id=domain_id)
        self.node = rclpy.create_node('eval_run_monitor', context=self.context)
        self.sim_now = None
        self.outcome = None   # (reason, stage, sim t)
        self.lock = threading.Lock()
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        clock_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.node.create_subscription(Clock, '/clock', self.on_clock, clock_qos)
        self.node.create_subscription(String, '/compliance/fsm_state', self.on_fsm, 50)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.spin, daemon=True)
        self.thread.start()

    def spin(self):
        while self.context.ok():
            try:
                self.executor.spin_once(timeout_sec=0.2)
            except Exception:  # noqa: BLE001 - context shut down mid-spin
                break

    def on_clock(self, msg):
        with self.lock:
            self.sim_now = msg.clock.sec + msg.clock.nanosec * 1e-9

    def on_fsm(self, msg):
        try:
            event = json.loads(msg.data)
        except ValueError:
            return
        if event.get('new_state') == 'MONITORING' and event.get('reason') in OUTCOMES:
            with self.lock:
                if self.outcome is None:
                    stamp = event.get('stamp')
                    self.outcome = (event['reason'], event.get('stage_reached'),
                                    round(stamp, 3) if stamp is not None else None)

    def state(self):
        with self.lock:
            return self.sim_now, self.outcome

    def close(self):
        self.executor.shutdown()
        self.node.destroy_node()
        self.rclpy.shutdown(context=self.context)


# --------------------------------------------------------------- one run

def stop_group(proc, log):
    """SIGINT (lets rosbag2 finalise) -> SIGTERM -> SIGKILL, whole group."""
    pgid = proc.pid
    for sig, wait in ((signal.SIGINT, 40), (signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            break
        deadline = time.time() + wait
        while time.time() < deadline and group_alive(pgid):
            time.sleep(0.5)
        if not group_alive(pgid):
            break
        log.write(f'\n[run_batch] group {pgid} still alive after {sig.name}\n')
    proc.wait(timeout=5)
    return not group_alive(pgid)


def group_alive(pgid):
    result = subprocess.run(['pgrep', '-g', str(pgid)], capture_output=True, text=True)
    return bool(result.stdout.strip())


def died_before(log_path, offset):
    """Processes that died before we stopped the run (crashes, not shutdown)."""
    with open(log_path, encoding='utf-8', errors='replace') as f:
        text = f.read(offset)
    died = []
    for line in text.splitlines():
        if 'process has died' in line:
            died.append(line.split('[')[1].split(']')[0] if '[' in line else line[:60])
    return sorted(set(died))


def config_applied(log_path, seed, ablation=None):
    """launch_ros ignores a parameter file it cannot open, so check the
    nodes actually report the overlay's values before trusting a run."""
    with open(log_path, encoding='utf-8', errors='replace') as f:
        text = f.read()
    applied = ('Scenario publisher: mode=world' in text
               and f'Human actor node: seed={seed},' in text)
    if ablation:  # both confirmation nodes must report the ablation
        applied = applied and text.count(f'ablations={ablation})') >= 2
    return applied


def nav2_ready(log_path):
    """Both Nav2 lifecycle managers (localization = map_server + AMCL, and
    navigation) reported their nodes active. Nav2 occasionally hangs during
    bring-up (AMCL configured but never activated); the robot then cannot
    localise or move, so such a run says nothing about the compliance system."""
    try:
        with open(log_path, encoding='utf-8', errors='replace') as f:
            lines = [ln for ln in f if 'Managed nodes are active' in ln]
    except OSError:
        return False
    return all(any(f'lifecycle_manager_{manager}]' in ln for ln in lines)
               for manager in ('localization', 'navigation'))


def quarantine(run_dir, reason):
    """Move a run that is about to be redone out of the way (never delete)."""
    if not os.path.isdir(run_dir):
        return None
    rel = os.path.relpath(run_dir, os.path.join(EVAL, 'data'))
    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    dest = os.path.join(EVAL, 'data', 'runs_invalid', f'{rel}__{stamp}__{reason}')
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    os.rename(run_dir, dest)
    return dest


def run_once(scenario, seed, run_dir, weights, domain_id, cli):
    run_dir = os.path.abspath(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, 'overlay.yaml'), 'w', encoding='utf-8') as f:
        f.write(f'# GENERATED by run_batch.py for {scenario["id"]} seed {seed}\n')
        yaml.safe_dump(build_overlay(scenario, seed, run_dir), f, sort_keys=False)
    cmd = ['ros2', 'launch', 'yoru_bringup', 'sim_full.launch.py',
           *launch_args(weights, cli.ablate),
           f'overlay_params:={os.path.join(run_dir, "overlay.yaml")}',
           f'bag_path:={os.path.join(run_dir, "bag")}']
    env = dict(os.environ, ROS_DOMAIN_ID=str(domain_id))
    for var in ('ROS_DISCOVERY_SERVER', 'ROS_SUPER_CLIENT'):
        env.pop(var, None)

    log_path = os.path.join(run_dir, 'launch.log')
    log = open(log_path, 'w', encoding='utf-8')
    log.write('[run_batch] ' + ' '.join(cmd) + '\n')
    log.flush()
    monitor = RunMonitor(domain_id)
    start = time.time()
    proc = subprocess.Popen(cmd, cwd=run_dir, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    max_sim = float(scenario['max_sim_s'])
    post = float(scenario.get('post_outcome_s', 10))
    wall_limit = cli.startup_timeout + max_sim / cli.min_rtf
    status = 'ok'
    checked_config = False
    checked_nav2 = False
    while True:
        time.sleep(1.0)
        sim_now, outcome = monitor.state()
        elapsed = time.time() - start
        if proc.poll() is not None:
            status = 'launch_exited'
            break
        if sim_now is None:
            if elapsed > cli.startup_timeout:
                status = 'startup_failed'
                break
            continue
        if not checked_config and elapsed > 20.0:
            checked_config = True
            if not config_applied(log_path, seed, cli.ablate):
                status = 'config_not_applied'
                break
        # Nav2 must be up before the violation onset (sim 30 s)
        if not checked_nav2 and sim_now >= cli.nav2_deadline:
            checked_nav2 = True
            if not nav2_ready(log_path):
                status = 'nav2_not_ready'
                break
        if outcome is not None and sim_now >= (outcome[2] or 0.0) + post:
            break
        if sim_now >= max_sim:
            break
        if elapsed > wall_limit:
            status = 'timeout'
            break
    log.flush()
    offset = os.path.getsize(log_path)
    sim_end, outcome = monitor.state()
    end = time.time()
    clean = stop_group(proc, log)
    monitor.close()
    log.close()
    if not clean:
        status = 'cleanup_failed' if status == 'ok' else status

    died = died_before(log_path, offset)
    bag_ok = os.path.isfile(os.path.join(run_dir, 'bag', 'metadata.yaml'))
    if status == 'ok' and not bag_ok:
        status = 'bag_missing'
    info = {
        'scenario': scenario['id'], 'seed': seed, 'status': status,
        'outcome': outcome[0] if outcome else 'none',
        'outcome_stage': outcome[1] if outcome else '',
        'outcome_sim_t': outcome[2] if outcome else '',
        'start_wall': datetime.datetime.fromtimestamp(start).isoformat(timespec='seconds'),
        'end_wall': datetime.datetime.fromtimestamp(end).isoformat(timespec='seconds'),
        'wall_s': round(end - start, 1), 'sim_s': round(sim_end or 0.0, 1),
        'rtf': round((sim_end or 0.0) / max(end - start - 1e-9, 1e-9), 3),
        'bag_ok': bag_ok, 'died_processes': ';'.join(died),
        'command': cmd, 'domain_id': domain_id,
    }
    with open(os.path.join(run_dir, 'run_info.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, indent=2)
    return info


# ------------------------------------------------------------------- main

def completed_runs(manifest):
    """Runs whose LATEST manifest row is 'ok' and whose log shows Nav2 came up
    (re-checked, so runs recorded before the readiness guard existed are
    re-validated too)."""
    if not os.path.isfile(manifest):
        return set(), {}
    latest = {}
    with open(manifest, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            latest[(r['tag'], r['scenario'], r['seed'])] = r
    done, invalid = set(), {}
    for key, r in latest.items():
        if r['status'] != 'ok':
            continue
        if nav2_ready(os.path.join(ROOT, r['run_dir'], 'launch.log')):
            done.add(key)
        else:
            invalid[key] = r
    return done, invalid


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--scenarios', default='all', help="comma list or 'all'")
    ap.add_argument('--seeds', type=int, default=20, help='seeds 0..N-1')
    ap.add_argument('--seed-list', help='explicit comma list of seeds (overrides --seeds)')
    ap.add_argument('--w-d', type=float)
    ap.add_argument('--w-p', type=float)
    ap.add_argument('--w-t', type=float)
    ap.add_argument('--w-s', type=float)
    ap.add_argument('--threshold', type=float,
                    help='confirm_confidence tau; uncertain band becomes [tau-0.2, tau)')
    ap.add_argument('--ablate', choices=('c4', 'c5', 'c7'),
                    help='Phase 7: disable C4 (persistence gate), C5 (support, w_S=0 '
                         'renormalised) or C7 (confounder rule) in both confirmation nodes')
    ap.add_argument('--tag', help='run-set name (default: baseline / weight string)')
    ap.add_argument('--out', default=os.path.join(EVAL, 'data', 'runs'))
    ap.add_argument('--manifest', default=os.path.join(EVAL, 'data', 'manifest.csv'))
    ap.add_argument('--retries', type=int, default=1,
                    help='re-run a startup/launch failure this many times')
    ap.add_argument('--skip-existing', action='store_true',
                    help="skip runs already 'ok' in the manifest (resume)")
    ap.add_argument('--startup-timeout', type=float, default=120.0,
                    help='wall s allowed until /clock appears')
    ap.add_argument('--min-rtf', type=float, default=0.4,
                    help='wall timeout = startup + max_sim_s / min_rtf')
    ap.add_argument('--nav2-deadline', type=float, default=28.0,
                    help='sim s by which Nav2 must report active (before the 30 s onset)')
    ap.add_argument('--dry-run', action='store_true')
    cli = ap.parse_args()
    cli.out = os.path.abspath(cli.out)
    cli.manifest = os.path.abspath(cli.manifest)

    scenarios = load_scenarios(cli.scenarios)
    seeds = ([int(s) for s in cli.seed_list.split(',')] if cli.seed_list
             else list(range(cli.seeds)))
    weights, tag = weight_settings(cli)
    if cli.ablate and not cli.tag:
        tag = f'ablate_{cli.ablate}' if tag == 'baseline' else f'{tag}_ablate_{cli.ablate}'
    plan = [(s, seed) for s in scenarios for seed in seeds]
    done, invalid = completed_runs(cli.manifest) if cli.skip_existing else (set(), {})
    for key in invalid:
        print(f'[run_batch] {"/".join(key)} was ok but Nav2 never came up: will redo',
              flush=True)
    fingerprint = code_fingerprint()
    print(f'[run_batch] tag={tag} runs={len(plan)} code={fingerprint} '
          f'weights={ {k: v for k, v in weights.items() if v is not None} }')
    if cli.dry_run:
        for s, seed in plan:
            print(f'  {s["id"]:8s} seed {seed}')
        return

    os.makedirs(os.path.dirname(cli.manifest), exist_ok=True)
    new_manifest = not os.path.isfile(cli.manifest)
    with open(cli.manifest, 'a', newline='', encoding='utf-8') as mf:
        writer = csv.DictWriter(mf, fieldnames=MANIFEST_FIELDS)
        if new_manifest:
            writer.writeheader()
        for index, (scenario, seed) in enumerate(plan):
            if (tag, scenario['id'], str(seed)) in done:
                print(f'[run_batch] skip {scenario["id"]} seed {seed} (already ok)')
                continue
            run_dir = os.path.join(cli.out, tag, scenario['id'], str(seed))
            for attempt in range(1, cli.retries + 2):
                domain_id = 60 + (index * 3 + attempt) % 40
                print(f'[run_batch] {index + 1}/{len(plan)} {scenario["id"]} seed {seed} '
                      f'attempt {attempt} (domain {domain_id}) -> {run_dir}', flush=True)
                if os.path.isdir(run_dir):
                    reason = ('nav2_not_ready_posthoc'
                              if (tag, scenario['id'], str(seed)) in invalid and attempt == 1
                              else 'superseded')
                    moved = quarantine(run_dir, reason)
                    print(f'[run_batch]   previous attempt moved to {moved}', flush=True)
                info = run_once(scenario, seed, run_dir, weights, domain_id, cli)
                print(f'[run_batch]   status={info["status"]} outcome={info["outcome"]} '
                      f'stage={info["outcome_stage"]} sim={info["sim_s"]}s '
                      f'wall={info["wall_s"]}s rtf={info["rtf"]}', flush=True)
                if info['status'] not in ('startup_failed', 'launch_exited',
                                          'config_not_applied', 'nav2_not_ready'):
                    break
                time.sleep(5)
            time.sleep(3)  # let DDS / shared memory settle between runs
            run_fingerprint = code_fingerprint()  # per run: catches mid-batch edits
            if run_fingerprint != fingerprint:
                print(f'[run_batch]   WARNING code changed during the batch: '
                      f'{fingerprint} -> {run_fingerprint}', flush=True)
            writer.writerow({
                'run_id': f'{tag}/{scenario["id"]}/{seed}', 'tag': tag,
                'scenario': scenario['id'], 'seed': seed,
                **{k: ('' if v is None else v) for k, v in weights.items()},
                'ablation': cli.ablate or '', 'status': info['status'], 'outcome': info['outcome'],
                'outcome_stage': info['outcome_stage'],
                'outcome_sim_t': info['outcome_sim_t'],
                'expected_outcome': scenario['expected_outcome'],
                'ground_truth': scenario['ground_truth'],
                'start_wall': info['start_wall'], 'end_wall': info['end_wall'],
                'wall_s': info['wall_s'], 'sim_s': info['sim_s'], 'rtf': info['rtf'],
                'attempts': attempt, 'bag_ok': info['bag_ok'],
                'died_processes': info['died_processes'],
                'code_sha256': run_fingerprint,
                'run_dir': os.path.relpath(run_dir, ROOT)})
            mf.flush()


if __name__ == '__main__':
    main()
