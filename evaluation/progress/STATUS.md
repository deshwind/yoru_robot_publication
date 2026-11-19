# Simulation progress: 2026-11-19 13:17:15

**Health: OK**

Batch runner: running for 02:00:24 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 1 (up 00:28)
Memory available: 3570 / 7795 MB, swap used 1 MB, disk free 945 GB, load 6.29
Failed attempts set aside (runs_invalid): 2

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 40 | 39 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| repro_wsl/H/2 | ok | target_lost | S2 | 55.3 | 68.1 | 0.812 | 2026-11-19T12:54:34 |
| repro_wsl/I/0 | ok | complied | S3 | 85.5 | 97.1 | 0.881 | 2026-11-19T12:56:41 |
| repro_wsl/I/1 | ok | complied | S3 | 87.8 | 99.1 | 0.886 | 2026-11-19T12:59:17 |
| repro_wsl/I/2 | ok | complied | S3 | 85.3 | 96.1 | 0.888 | 2026-11-19T13:01:55 |
| repro_wsl/J/0 | ok | complied | S3 | 85.4 | 96.1 | 0.889 | 2026-11-19T13:04:30 |
| repro_wsl/J/1 | ok | none |  | 190.7 | 214.3 | 0.89 | 2026-11-19T13:07:05 |
| repro_wsl/J/2 | ok | complied | S3 | 85.7 | 102.1 | 0.839 | 2026-11-19T13:11:38 |
| repro_wsl/K/0 | ok | safety_stop | S2 | 74.3 | 89.1 | 0.834 | 2026-11-19T13:14:19 |

Newest run: `evaluation/data/repro/repro_wsl/K/0/run_info.json`: status ok, RTF 0.834, sim 74.3 s, wall 89.1 s

Newest launch log: `evaluation/data/repro/repro_wsl/K/1/launch.log`
