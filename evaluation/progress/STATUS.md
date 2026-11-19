# Simulation progress: 2026-11-19 13:02:16

**Health: OK**

Batch runner: running for 01:45:25 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 1 (up 00:20)
Memory available: 3616 / 7795 MB, swap used 1 MB, disk free 945 GB, load 9.90
Failed attempts set aside (runs_invalid): 2

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 35 | 34 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| repro_wsl/G/0 | ok | logged_no_compliance | S4 | 98.8 | 110.1 | 0.897 | 2026-11-19T12:41:49 |
| repro_wsl/G/1 | ok | logged_no_compliance | S4 | 99.8 | 111.1 | 0.898 | 2026-11-19T12:44:38 |
| repro_wsl/G/2 | ok | logged_no_compliance | S4 | 99.1 | 110.1 | 0.9 | 2026-11-19T12:47:28 |
| repro_wsl/H/0 | ok | target_lost | S2 | 55.9 | 65.1 | 0.859 | 2026-11-19T12:50:17 |
| repro_wsl/H/1 | ok | target_lost | S2 | 55.4 | 75.1 | 0.738 | 2026-11-19T12:52:21 |
| repro_wsl/H/2 | ok | target_lost | S2 | 55.3 | 68.1 | 0.812 | 2026-11-19T12:54:34 |
| repro_wsl/I/0 | ok | complied | S3 | 85.5 | 97.1 | 0.881 | 2026-11-19T12:56:41 |
| repro_wsl/I/1 | ok | complied | S3 | 87.8 | 99.1 | 0.886 | 2026-11-19T12:59:17 |

Newest run: `evaluation/data/repro/repro_wsl/I/1/run_info.json`: status ok, RTF 0.886, sim 87.8 s, wall 99.1 s

Newest launch log: `evaluation/data/repro/repro_wsl/I/2/launch.log`
