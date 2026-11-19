"""Gentle batch: the session rules that protect the laptop (2026-11-19).

Run:  python3 -m pytest evaluation/tests -q
"""

import csv
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import gentle_batch as gb  # noqa: E402
import run_batch as rb  # noqa: E402

DAY = datetime.date(2026, 11, 19)


def at(hms):
    return datetime.datetime.combine(DAY, datetime.time.fromisoformat(hms))


# Lines as written by host_monitor.sh on 2026-11-19 (evidence/machine_change/host_monitor_repro.log)
MONITOR = """# time | win_cpu_performance% | win_cpu_utility% | top Windows processes (% of one core) | linux load | mem_avail_MB | shm_files
12:12:40 | 101 | 89 | vmmemwsl=822 system=298 battle.net=86 | 18.38 | 3712 | 811
12:13:46 | 98 | 84 | vmmemwsl=816 system=214 battle.net=57 | 14.36 | 3645 | 811
12:14:51 | 99 | 87 | system=200 battle.net=31 agent=29 | 12.31 | 5888 | 654
12:22:30 | 94 | 19 | vmmemwsl=926 riotclientservices=79 system=62 | 3.17 | 5052 | 849
13:01:33 | 72 | 5 | system=38 svchost=14 cefsharp.browsersubprocess=8 | 3.66 | 6039 | 1078
13:28:37 monitored process 36773 exited; monitor stopped
"""


@pytest.fixture
def monitor_log(tmp_path):
    path = tmp_path / 'host_monitor.log'
    path.write_text(MONITOR)
    return str(path)


# ------------------------------------------------------------ monitor

def test_samples_are_read_within_the_window(monitor_log):
    s = gb.monitor_samples(monitor_log, at('12:13:00'), at('12:20:00'))
    assert [(t.strftime('%H:%M:%S'), p, u) for t, p, u in s] == \
        [('12:13:46', 98.0, 84.0), ('12:14:51', 99.0, 87.0)]


def test_missing_monitor_log_gives_no_samples(tmp_path):
    assert gb.monitor_samples(str(tmp_path / 'none.log'), at('12:00:00'), at('13:00:00')) == []


def test_normal_busy_run_is_not_throttled(monitor_log):
    s = gb.monitor_samples(monitor_log, at('12:00:00'), at('12:20:00'))
    assert gb.throttled(s, 85.0) == (False, 99.0)


def test_idle_samples_are_ignored(monitor_log):
    # 13:01:33 shows 72 % but the CPU was idle (utility 5 %): not throttling
    s = gb.monitor_samples(monitor_log, at('12:20:00'), at('13:10:00'))
    assert gb.throttled(s, 85.0) == (False, None)


def test_low_performance_while_busy_is_throttling():
    s = [(at('14:00:00'), 70.0, 90.0), (at('14:01:00'), 75.0, 88.0), (at('14:02:00'), 99.0, 20.0)]
    assert gb.throttled(s, 85.0) == (True, 72.5)


def test_one_low_sample_is_not_enough():
    assert gb.throttled([(at('14:00:00'), 60.0, 90.0)], 85.0) == (False, None)


# ------------------------------------------------------------ stopping

BASE = dict(elapsed_min=10, max_minutes=60, failures=0, max_failures=2, throttle=False,
            stop_file_present=False)


@pytest.mark.parametrize('change, expect', [
    ({}, None),
    ({'elapsed_min': 60}, 'time budget'),
    ({'failures': 2}, 'failed runs in a row'),
    ({'failures': 1}, None),
    ({'throttle': True}, 'throttling'),
    ({'stop_file_present': True}, 'STOP file'),
    ({'stop_file_present': True, 'throttle': True}, 'STOP file'),   # manual stop first
])
def test_stop_reason(change, expect):
    reason = gb.stop_reason(**{**BASE, **change})
    assert (reason is None) if expect is None else (expect in reason)


# ------------------------------------------------------------ resuming

def write_manifest(path, rows):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rb.MANIFEST_FIELDS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


def row(tag, scenario, seed, status):
    return {'run_id': f'{tag}/{scenario}/{seed}', 'tag': tag, 'scenario': scenario,
            'seed': seed, 'status': status, 'outcome': 'complied', 'outcome_stage': 'S3',
            'outcome_sim_t': '71.1', 'rtf': '0.85'}


def test_pending_skips_ok_runs_and_redoes_failed_ones(tmp_path):
    m = str(tmp_path / 'manifest.csv')
    write_manifest(m, [row('aware_hold_s1', 'H', 0, 'ok'),
                       row('aware_hold_s1', 'H', 1, 'nav2_not_ready'),
                       row('aware_hold_s1', 'H', 2, 'nav2_not_ready'),
                       row('aware_hold_s1', 'H', 2, 'ok'),          # redone later: latest wins
                       row('baseline', 'H', 3, 'ok')])               # other run set
    plan = [('H', s) for s in range(4)]
    assert gb.pending_runs(plan, m, 'aware_hold_s1') == [('H', 1), ('H', 3)]


def test_pending_without_manifest_is_the_whole_plan(tmp_path):
    plan = [('H', 0), ('C', 0)]
    assert gb.pending_runs(plan, str(tmp_path / 'none.csv'), 'x') == plan


def test_last_row_is_the_latest_attempt(tmp_path):
    m = str(tmp_path / 'manifest.csv')
    write_manifest(m, [row('t', 'H', 1, 'nav2_not_ready'), row('t', 'H', 1, 'ok')])
    assert gb.last_row(m, 't/H/1')['status'] == 'ok'
    assert gb.last_row(m, 't/H/9') is None


def test_tag_matches_run_batch():
    assert gb.run_tag(None, rb.variant_settings(compliance_aware='hold_s1')) == 'aware_hold_s1'
    assert gb.run_tag(None, rb.variant_settings()) == 'baseline'
    assert gb.run_tag('mine', rb.variant_settings(skip_pa=True)) == 'mine'


def test_monitor_lines_with_thermal_columns_are_read(tmp_path):
    # host_monitor.sh format from 2026-11-19 16:41: thermal zone and passive limit appended
    path = tmp_path / 'host_monitor.log'
    path.write_text('16:41:22 | 88 | 8 | code=16 cefsharp.browsersubprocess=10 code=10 | 0.58 | '
                    '9349 | 134 | 42.9 | 100\n')
    assert [(p, u) for _, p, u in gb.monitor_samples(str(path), at('16:40:00'), at('16:42:00'))] \
        == [(88.0, 8.0)]
