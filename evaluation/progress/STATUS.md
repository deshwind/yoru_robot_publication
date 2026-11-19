# Simulation progress: 2026-11-19 12:32:16

**Health: OK**

Batch runner: running for 01:15:25 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 1 (up 00:07)
Memory available: 3778 / 7795 MB, swap used 1 MB, disk free 945 GB, load 3.41
Failed attempts set aside (runs_invalid): 2

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 24 | 23 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| repro_wsl/D/1 | ok | none |  | 120.6 | 146.2 | 0.825 | 2026-11-19T12:05:30 |
| repro_wsl/D/2 | ok | none |  | 120.1 | 147.2 | 0.816 | 2026-11-19T12:08:55 |
| repro_wsl/E/0 | ok | none |  | 120.2 | 147.2 | 0.817 | 2026-11-19T12:12:21 |
| repro_wsl/E/1 | ok | none |  | 120.3 | 146.2 | 0.823 | 2026-11-19T12:15:47 |
| repro_wsl/E/2 | ok | none |  | 120.8 | 137.1 | 0.881 | 2026-11-19T12:19:12 |
| repro_wsl/F-pen/0 | ok | none |  | 120.3 | 138.1 | 0.871 | 2026-11-19T12:22:27 |
| repro_wsl/F-pen/1 | ok | none |  | 120.1 | 132.1 | 0.909 | 2026-11-19T12:25:44 |
| repro_wsl/F-pen/2 | ok | none |  | 120.7 | 134.2 | 0.9 | 2026-11-19T12:28:55 |

Newest run: `evaluation/data/repro/repro_wsl/F-pen/2/run_info.json`: status ok, RTF 0.9, sim 120.7 s, wall 134.2 s

Newest launch log: `evaluation/data/repro/repro_wsl/F-straw/0/launch.log`
