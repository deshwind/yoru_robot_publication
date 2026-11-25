"""Tests of archive_recordings.py (2026-11-25): deterministic archives, --only, and per-run
archives for the baseline re-run (so git does not keep a copy of a growing archive per seed)."""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import archive_recordings as ar  # noqa: E402


def make_run(root, scenario, run, text, finished=True):
    d = os.path.join(root, scenario, str(run))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'launch.log'), 'w') as f:
        f.write(text)
    if finished:
        with open(os.path.join(d, 'run_info.json'), 'w') as f:
            f.write(text)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    data, out = tmp_path / 'data', tmp_path / 'recordings'
    monkeypatch.setattr(ar, 'DATA', str(data))
    monkeypatch.setattr(ar, 'OUT', str(out))
    make_run(data / 'repro' / 'repro_wsl', 'A', 0, '{"r": 0}')
    make_run(data / 'baseline_wsl' / 'baseline_wsl', 'A', 3, '{"b": 3}')
    make_run(data / 'runs_invalid' / 'variants' / 'aware_both', 'A', '9__x', '{"f": 9}')
    return data, out


def test_packing_twice_gives_identical_files(tree):
    data, out = tree
    ar.pack()
    first = (out / 'repro_wsl' / 'A.tar.gz').read_bytes()
    ar.pack()
    assert (out / 'repro_wsl' / 'A.tar.gz').read_bytes() == first


def test_baseline_runs_get_one_archive_each(tree):
    data, out = tree
    make_run(data / 'baseline_wsl' / 'baseline_wsl', 'A', 4, '{"b": 4}')
    ar.pack()
    assert (out / 'baseline_wsl' / 'A' / '3.tar.gz').is_file()
    assert (out / 'baseline_wsl' / 'A' / '4.tar.gz').is_file()
    assert not (out / 'baseline_wsl' / 'A.tar.gz').exists()


def test_existing_run_archive_is_not_rewritten(tree):
    data, out = tree
    ar.pack()
    target = out / 'baseline_wsl' / 'A' / '3.tar.gz'
    before = target.stat().st_mtime_ns
    make_run(data / 'baseline_wsl' / 'baseline_wsl', 'A', 4, '{"b": 4}')
    ar.pack({'baseline_wsl'})
    assert target.stat().st_mtime_ns == before
    assert (out / 'baseline_wsl' / 'A' / '4.tar.gz').is_file()


def test_redone_run_is_repacked(tree):
    data, out = tree
    ar.pack()
    target = out / 'baseline_wsl' / 'A' / '3.tar.gz'
    before = target.read_bytes()
    time.sleep(0.02)
    make_run(data / 'baseline_wsl' / 'baseline_wsl', 'A', 3, '{"b": "redone"}')
    os.utime(data / 'baseline_wsl' / 'baseline_wsl' / 'A' / '3' / 'run_info.json',
             (time.time() + 5, time.time() + 5))
    ar.pack()
    assert target.read_bytes() != before


def test_unfinished_run_is_skipped(tree):
    data, out = tree
    make_run(data / 'baseline_wsl' / 'baseline_wsl', 'B', 3, 'running', finished=False)
    ar.pack()
    assert not (out / 'baseline_wsl' / 'B' / '3.tar.gz').exists()


def test_baseline_failed_attempts_are_archived_apart_from_misc(tree):
    data, out = tree
    ar.pack()
    misc_before = (out / 'misc' / 'runs_invalid.tar.gz').read_bytes()
    make_run(data / 'runs_invalid' / 'baseline_wsl' / 'baseline_wsl', 'C', '3__t__nav2', '{"x": 1}')
    ar.pack()
    assert (out / 'misc' / 'runs_invalid.tar.gz').read_bytes() == misc_before
    assert (out / 'baseline_wsl' / 'failed_attempts' / 'C' / '3__t__nav2.tar.gz').is_file()


def test_only_repacks_the_selected_group(tree):
    data, out = tree
    ar.pack()
    repro_before = (out / 'repro_wsl' / 'A.tar.gz').read_bytes()
    make_run(data / 'repro' / 'repro_wsl', 'A', 1, '{"r": 1}')          # not selected
    make_run(data / 'baseline_wsl' / 'baseline_wsl', 'A', 4, '{"b": 4}')  # selected
    ar.pack({'baseline_wsl'})
    assert (out / 'repro_wsl' / 'A.tar.gz').read_bytes() == repro_before
    assert (out / 'baseline_wsl' / 'A' / '4.tar.gz').is_file()
    ar.pack()                                                              # full pack catches up
    assert (out / 'repro_wsl' / 'A.tar.gz').read_bytes() != repro_before


def test_only_still_packs_a_group_without_an_archive(tree):
    data, out = tree
    ar.pack({'baseline_wsl'})
    assert (out / 'repro_wsl' / 'A.tar.gz').is_file()


def test_readme_lists_every_group(tree):
    data, out = tree
    ar.pack()
    ar.pack({'baseline_wsl'})
    readme = (out / 'README.md').read_text()
    assert 'repro_wsl/A.tar.gz' in readme and '| baseline_wsl | [`baseline_wsl/A`]' in readme
