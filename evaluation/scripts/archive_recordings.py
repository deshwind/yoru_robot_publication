#!/usr/bin/env python3
"""Pack the run recordings into deterministic compressed archives that are committed to git.

The 300 baseline recordings were lost with the laptop's failed drive (evidence/README.md).
Since 2026-11-24 every recording made on the laptop is committed to the repository as
compressed archives (decision of the user), one archive per run set and scenario:

  evaluation/data/repro/repro_wsl/<S>/          -> evaluation/recordings/repro_wsl/<S>.tar.gz
  evaluation/data/variants/<tag>/<S>/           -> evaluation/recordings/<tag>/<S>.tar.gz
  evaluation/data/baseline_wsl/baseline_wsl/<S>/<seed>/ -> evaluation/recordings/baseline_wsl/<S>/<seed>.tar.gz
  evaluation/data/runs_invalid/baseline_wsl/baseline_wsl/<S>/<attempt>/
                                     -> evaluation/recordings/baseline_wsl/failed_attempts/<S>/<attempt>.tar.gz
  evaluation/data/{pilot,doc,phase_b,runs_invalid}/ -> evaluation/recordings/misc/<name>.tar.gz

plus each run set's manifest.csv and batch.log as plain files.

The baseline re-run (255 runs over about six days) gets ONE ARCHIVE PER RUN instead (decided
2026-11-25): a per-scenario archive would be rewritten after every new seed, and git keeps every
version in full (about 5.9 GB of history over the re-run, against about 650 MB per run). A per-run
archive is written once, when the run has finished (its run_info.json exists), and is repacked only
if the run is redone (run_info.json newer than the archive). Its failed attempts are archived the
same way and kept out of misc/runs_invalid.tar.gz, which therefore stays as it was. Archives are deterministic
(sorted entries, fixed times and owners, gzip without a timestamp), so packing unchanged data
again gives byte-identical files and git stores nothing new. An archive is rewritten only when
its content changed. Writes evaluation/recordings/CHECKSUMS.sha256 and the table in
evaluation/recordings/README.md.

  python3 evaluation/scripts/archive_recordings.py            # pack / update
  python3 evaluation/scripts/archive_recordings.py --verify   # check archives against CHECKSUMS
  python3 evaluation/scripts/archive_recordings.py --only baseline_wsl   # repack one group only

--only (added 2026-11-25 for the 30-minute saves during the baseline re-run): repack only the
named groups (comma-separated; `misc` for the misc archives). Other existing archives are left
as they are, unread, so a save takes seconds instead of about 20 s of compression; a group whose
archive does not exist yet is still packed.

Restore one archive:  tar -xzf evaluation/recordings/repro_wsl/A.tar.gz -C evaluation/data/repro/repro_wsl
"""

import csv
import gzip
import hashlib
import io
import os
import shutil
import sys
import tarfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DATA = os.path.join(ROOT, 'evaluation', 'data')
OUT = os.path.join(ROOT, 'evaluation', 'recordings')
FIXED_MTIME = 1767225600   # 2026-01-01 00:00:00 UTC

# (group, directory holding one folder per scenario, folder with manifest.csv / batch.log)
SCENARIO_SETS = [
    ('repro_wsl', 'repro/repro_wsl', 'repro'),
    ('aware_hold_s1', 'variants/aware_hold_s1', 'variants'),
    ('aware_reset_first', 'variants/aware_reset_first', 'variants'),
    ('aware_both', 'variants/aware_both', 'variants'),
]
MISC = ['pilot', 'doc', 'phase_b', 'runs_invalid']
# (group, runs directory, folder with manifest.csv / batch.log, failed-attempts directory)
PER_RUN_SETS = [
    ('baseline_wsl', 'baseline_wsl/baseline_wsl', 'baseline_wsl',
     'runs_invalid/baseline_wsl/baseline_wsl'),
]
# kept out of the misc archive of the same name (archived per attempt instead)
MISC_EXCLUDE = {'runs_invalid': [os.path.relpath(s[3], 'runs_invalid').split(os.sep)[0]
                                 for s in PER_RUN_SETS]}


def deterministic_tar_gz(src_parent, name, exclude=()):
    """Bytes of a .tar.gz of src_parent/name that depend only on the content.
    exclude: subdirectories of src_parent/name (relative to it) left out."""
    raw = io.BytesIO()
    top = os.path.join(src_parent, name)
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.GNU_FORMAT) as tar:
        paths = []
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames
                                 if os.path.relpath(os.path.join(dirpath, d), top) not in exclude)
            paths.append(dirpath)
            paths += [os.path.join(dirpath, f) for f in sorted(filenames)]
        for path in sorted(paths):
            info = tar.gettarinfo(path, arcname=os.path.relpath(path, src_parent))
            info.mtime, info.uid, info.gid, info.uname, info.gname = FIXED_MTIME, 0, 0, '', ''
            info.mode = 0o755 if info.isdir() else 0o644
            if info.isfile():
                with open(path, 'rb') as f:
                    tar.addfile(info, f)
            elif info.isdir():
                tar.addfile(info)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode='wb', compresslevel=6, mtime=0, filename='') as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def du(path):
    total = 0
    for dirpath, _, filenames in os.walk(path):
        total += sum(os.path.getsize(os.path.join(dirpath, f)) for f in filenames)
    return total


def count_runs(path):
    return sum(1 for _, _, files in os.walk(path) if 'run_info.json' in files)


def write_if_changed(path, data):
    if os.path.isfile(path):
        with open(path, 'rb') as f:
            if f.read() == data:
                return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return True


def _existing(target, only, group):
    """True when this archive is to be left as it is (not selected by --only, and present)."""
    return only is not None and group not in only and os.path.isfile(target)


def pack_per_run(group, rel, meta, invalid_rel, only=None):
    """One archive per finished run (and per failed attempt); README rows per scenario."""
    selected = only is None or group in only
    changed, rows = 0, []
    for src_rel, sub in ((rel, ''), (invalid_rel, 'failed_attempts')):
        base = os.path.join(DATA, src_rel)
        if not os.path.isdir(base):
            continue
        for scenario in sorted(os.listdir(base)):
            sdir = os.path.join(base, scenario)
            if not os.path.isdir(sdir):
                continue
            runs = raw = comp = 0
            for run in sorted(os.listdir(sdir)):
                info = os.path.join(sdir, run, 'run_info.json')
                if not os.path.isfile(info):          # not a run, or not finished yet
                    continue
                target = os.path.join(OUT, group, sub, scenario, f'{run}.tar.gz')
                if os.path.isfile(target) and (not selected or
                                               os.path.getmtime(target) >= os.path.getmtime(info)):
                    size = os.path.getsize(target)
                else:
                    data = deterministic_tar_gz(base, os.path.join(scenario, run))
                    changed += write_if_changed(target, data)
                    size = len(data)
                runs, raw, comp = runs + 1, raw + du(os.path.join(sdir, run)), comp + size
            if runs:
                rows.append((group, os.path.join(sub, scenario) if sub else scenario, runs, raw,
                             comp, os.path.join(OUT, group, sub, scenario)))
    if selected:
        for name in ('manifest.csv', 'batch.log'):
            src = os.path.join(DATA, meta, name)
            if os.path.isfile(src):
                with open(src, 'rb') as f:
                    changed += write_if_changed(os.path.join(OUT, group, name), f.read())
    return changed, rows


def pack(only=None):
    rows, changed = [], 0
    for group, rel, meta in SCENARIO_SETS:
        base = os.path.join(DATA, rel)
        if not os.path.isdir(base):
            continue
        for scenario in sorted(os.listdir(base)):
            if not os.path.isdir(os.path.join(base, scenario)):
                continue
            target = os.path.join(OUT, group, f'{scenario}.tar.gz')
            if _existing(target, only, group):
                size = os.path.getsize(target)
            else:
                data = deterministic_tar_gz(base, scenario)
                changed += write_if_changed(target, data)
                size = len(data)
            rows.append((group, scenario, count_runs(os.path.join(base, scenario)),
                         du(os.path.join(base, scenario)), size, target))
        for name in ('manifest.csv', 'batch.log'):
            src = os.path.join(DATA, meta, name)
            if os.path.isfile(src):
                with open(src, 'rb') as f:
                    changed += write_if_changed(os.path.join(OUT, group, name), f.read())
    for name in MISC:
        src = os.path.join(DATA, name)
        if os.path.isdir(src):
            target = os.path.join(OUT, 'misc', f'{name}.tar.gz')
            if _existing(target, only, 'misc'):
                size = os.path.getsize(target)
            else:
                data = deterministic_tar_gz(DATA, name, MISC_EXCLUDE.get(name, ()))
                changed += write_if_changed(target, data)
                size = len(data)
            excluded = [os.path.join(src, e) for e in MISC_EXCLUDE.get(name, ())]
            rows.append(('misc', name, count_runs(src) - sum(count_runs(e) for e in excluded),
                         du(src) - sum(du(e) for e in excluded), size, target))
    for group, rel, meta, invalid_rel in PER_RUN_SETS:
        n, new_rows = pack_per_run(group, rel, meta, invalid_rel, only)
        changed += n
        rows += new_rows
    sums = []
    for dirpath, _, filenames in os.walk(OUT):
        for f in sorted(filenames):
            if f.endswith('.tar.gz'):
                p = os.path.join(dirpath, f)
                with open(p, 'rb') as fh:
                    sums.append(f'{hashlib.sha256(fh.read()).hexdigest()}  {os.path.relpath(p, OUT)}')
    write_if_changed(os.path.join(OUT, 'CHECKSUMS.sha256'), ('\n'.join(sorted(sums, key=lambda l: l[66:])) + '\n').encode())
    write_readme(rows)
    print(f'{len(rows)} archives, {changed} file(s) written or updated; '
          f'raw {sum(r[3] for r in rows) / 2**20:.0f} MB -> {sum(r[4] for r in rows) / 2**20:.0f} MB')


def write_readme(rows):
    lines = ['# Run recordings (compressed)', '',
             'The rosbag2 recordings and run folders of every run made on the laptop since the',
             'original baseline recordings were lost (see `evidence/README.md`, "Same laptop, new operating',
             'system"). One deterministic `.tar.gz` per run set and scenario, made by',
             '[`archive_recordings.py`](../scripts/archive_recordings.py); each holds the run folders',
             '(`bag/`, `launch.log`, `overlay.yaml`, `run_info.json`, `incident_logs/`) exactly as the runner',
             'wrote them under `evaluation/data/`. Checksums: [`CHECKSUMS.sha256`](CHECKSUMS.sha256)',
             '(`cd evaluation/recordings && sha256sum -c CHECKSUMS.sha256`).', '',
             '**Restore** (for example to re-run `extract_metrics.py` on them):', '',
             '```bash',
             'tar -xzf evaluation/recordings/repro_wsl/A.tar.gz -C evaluation/data/repro/repro_wsl',
             'tar -xzf evaluation/recordings/aware_hold_s1/H.tar.gz -C evaluation/data/variants/aware_hold_s1',
             'tar -xzf evaluation/recordings/misc/runs_invalid.tar.gz -C evaluation/data',
             'tar -xzf evaluation/recordings/baseline_wsl/A/3.tar.gz -C evaluation/data/baseline_wsl/baseline_wsl',
             '```', '',
             'The baseline re-run (`baseline_wsl`) has **one archive per run** (`baseline_wsl/<scenario>/<seed>.tar.gz`,',
             'failed attempts in `baseline_wsl/failed_attempts/`): each is written once, so git does not keep a new',
             'copy of a growing archive after every seed. The table counts them per scenario.', '',
             '| Run set | Archive | Runs (valid + failed attempts) | Raw | Compressed |',
             '|---|---|---|---|---|']
    for group, name, runs, raw, comp, target in rows:
        lines.append(f'| {group} | [`{os.path.relpath(target, OUT)}`]({os.path.relpath(target, OUT)}) | '
                     f'{runs} | {raw / 2**20:.1f} MB | {comp / 2**20:.1f} MB |')
    lines += ['', f'Total: {sum(r[2] for r in rows)} run folders, {sum(r[3] for r in rows) / 2**20:.0f} MB raw, '
              f'{sum(r[4] for r in rows) / 2**20:.0f} MB compressed.', '',
              'Run sets: `repro_wsl` = the 45-run reproduction (scenarios × seeds 0–2); `aware_*` = Phase C',
              'FSM-variant sets; `baseline_wsl` = the baseline re-run (seeds 3–19); `misc` = pilot and',
              'diagnostic runs (`pilot`), the documentation run (`doc`), the Phase B check run (`phase_b`)',
              'and every failed attempt set aside by the runner (`runs_invalid`).', '']
    write_if_changed(os.path.join(OUT, 'README.md'), '\n'.join(lines).encode())


def verify():
    bad = 0
    with open(os.path.join(OUT, 'CHECKSUMS.sha256')) as f:
        for line in f:
            digest, rel = line.split()
            with open(os.path.join(OUT, rel), 'rb') as fh:
                ok = hashlib.sha256(fh.read()).hexdigest() == digest
            bad += not ok
            if not ok:
                print('MISMATCH', rel)
    print('all archives verified' if not bad else f'{bad} archive(s) do not match')
    return bad


def main(argv):
    if '--verify' in argv:
        return 1 if verify() else 0
    only = None
    if '--only' in argv:
        only = set(argv[argv.index('--only') + 1].split(','))
    pack(only)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
