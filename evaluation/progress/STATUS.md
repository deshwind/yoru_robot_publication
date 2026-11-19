# Simulation progress: 2026-11-19 12:03:51

**Health: OK**

Batch runner: running for 47:00 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 1 (up 01:53)
Memory available: 3638 / 7795 MB, swap used 1 MB, disk free 945 GB, load 15.75
Failed attempts set aside (runs_invalid): 2

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 15 | 14 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| repro_wsl/B/1 | ok | none |  | 120.0 | 168.3 | 0.713 | 2026-11-19T11:36:34 |
| repro_wsl/B/2 | ok | none |  | 120.5 | 156.3 | 0.771 | 2026-11-19T11:40:21 |
| repro_wsl/B-C7/0 | ok | logged_no_compliance | S4 | 99.7 | 140.2 | 0.711 | 2026-11-19T11:43:56 |
| repro_wsl/B-C7/1 | nav2_not_ready | none |  | 28.6 | 48.1 | 0.595 | 2026-11-19T11:49:00 |
| repro_wsl/B-C7/2 | ok | logged_no_compliance | S4 | 101.2 | 156.3 | 0.648 | 2026-11-19T11:50:52 |
| repro_wsl/C/0 | ok | target_lost | S2 | 62.3 | 92.2 | 0.676 | 2026-11-19T11:54:27 |
| repro_wsl/C/1 | ok | target_lost | S2 | 62.4 | 92.2 | 0.677 | 2026-11-19T11:56:58 |
| repro_wsl/C/2 | ok | target_lost | S2 | 64.2 | 90.1 | 0.712 | 2026-11-19T11:59:29 |

Newest run: `evaluation/data/repro/repro_wsl/C/2/run_info.json`: status ok, RTF 0.712, sim 64.2 s, wall 90.1 s

Newest launch log: `evaluation/data/repro/repro_wsl/D/0/launch.log`
