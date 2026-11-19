# Simulation progress: 2026-11-19 11:17:49

**Health: OK**

Batch runner: running for 00:58 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 1 (up 00:56)
Memory available: 3653 / 7795 MB, swap used 1 MB, disk free 945 GB, load 10.45
Failed attempts set aside (runs_invalid): 1

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 0 | 0 | - |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| baseline/L/18 | ok | admin_override | S2 | 55.0 | 60.1 | 0.916 | 2026-10-12T20:08:51 |
| baseline/L/19 | ok | admin_override | S2 | 54.5 | 60.1 | 0.907 | 2026-10-12T20:10:50 |
| baseline/K/1 | ok | safety_stop | S2 | 74.1 | 80.1 | 0.925 | 2026-10-12T20:24:21 |
| wsl_pilot_nvidia/A/0 | nav2_not_ready | none |  | 28.2 | 167.8 | 0.168 | 2026-11-19T10:44:45 |
| wsl_pilot_clockfix/A/0 | ok | complied | S3 | 86.7 | 152.2 | 0.57 | 2026-11-19T10:53:19 |
| wsl_pilot_perf/A/0 | ok | complied | S3 | 86.3 | 157.3 | 0.548 | 2026-11-19T10:58:36 |
| wsl_threads2/A/0 | ok | complied | S3 | 84.9 | 106.1 | 0.8 | 2026-11-19T11:05:54 |
| doc_pictures/A/0 | ok | complied | S3 | 85.5 | 115.2 | 0.742 | 2026-11-19T11:09:08 |

Newest run: `evaluation/data/doc/doc_pictures/A/0/run_info.json`: status ok, RTF 0.742, sim 85.5 s, wall 115.2 s

Newest launch log: `evaluation/data/repro/repro_wsl/A/0/launch.log`
