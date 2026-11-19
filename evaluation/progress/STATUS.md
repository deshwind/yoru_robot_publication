# Simulation progress: 2026-11-19 13:32:15

**Health: OK**

Batch runner: not running
Gazebo servers: 0
Memory available: 6060 / 7795 MB, swap used 1 MB, disk free 944 GB, load 0.35
Failed attempts set aside (runs_invalid): 2

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 45 | 44 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| repro_wsl/J/1 | ok | none |  | 190.7 | 214.3 | 0.89 | 2026-11-19T13:07:05 |
| repro_wsl/J/2 | ok | complied | S3 | 85.7 | 102.1 | 0.839 | 2026-11-19T13:11:38 |
| repro_wsl/K/0 | ok | safety_stop | S2 | 74.3 | 89.1 | 0.834 | 2026-11-19T13:14:19 |
| repro_wsl/K/1 | ok | safety_stop | S2 | 73.8 | 89.1 | 0.828 | 2026-11-19T13:16:47 |
| repro_wsl/K/2 | ok | safety_stop | S2 | 74.0 | 89.1 | 0.83 | 2026-11-19T13:19:14 |
| repro_wsl/L/0 | ok | admin_override | S2 | 54.3 | 71.1 | 0.764 | 2026-11-19T13:21:42 |
| repro_wsl/L/1 | ok | admin_override | S2 | 55.1 | 65.1 | 0.847 | 2026-11-19T13:23:52 |
| repro_wsl/L/2 | ok | admin_override | S2 | 54.6 | 64.1 | 0.852 | 2026-11-19T13:25:56 |

Newest run: `evaluation/data/repro/repro_wsl/L/2/run_info.json`: status ok, RTF 0.852, sim 54.6 s, wall 64.1 s

Newest launch log: `evaluation/data/repro/repro_wsl/L/2/launch.log`
