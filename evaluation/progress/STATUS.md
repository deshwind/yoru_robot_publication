# Simulation progress: 2026-11-19 12:47:15

**Health: OK**

Batch runner: running for 01:30:24 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 0
Memory available: 6028 / 7795 MB, swap used 1 MB, disk free 945 GB, load 4.58
Failed attempts set aside (runs_invalid): 2

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 28 | 27 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| repro_wsl/E/2 | ok | none |  | 120.8 | 137.1 | 0.881 | 2026-11-19T12:19:12 |
| repro_wsl/F-pen/0 | ok | none |  | 120.3 | 138.1 | 0.871 | 2026-11-19T12:22:27 |
| repro_wsl/F-pen/1 | ok | none |  | 120.1 | 132.1 | 0.909 | 2026-11-19T12:25:44 |
| repro_wsl/F-pen/2 | ok | none |  | 120.7 | 134.2 | 0.9 | 2026-11-19T12:28:55 |
| repro_wsl/F-straw/0 | ok | none |  | 120.3 | 136.1 | 0.884 | 2026-11-19T12:32:08 |
| repro_wsl/F-straw/1 | ok | none |  | 120.4 | 135.1 | 0.891 | 2026-11-19T12:35:23 |
| repro_wsl/F-straw/2 | ok | none |  | 120.5 | 133.1 | 0.905 | 2026-11-19T12:38:37 |
| repro_wsl/G/0 | ok | logged_no_compliance | S4 | 98.8 | 110.1 | 0.897 | 2026-11-19T12:41:49 |

Newest run: `evaluation/data/repro/repro_wsl/G/0/run_info.json`: status ok, RTF 0.897, sim 98.8 s, wall 110.1 s

Newest launch log: `evaluation/data/repro/repro_wsl/G/1/launch.log`

```
[ERROR] [admin_joy_node-26]: process has died [pid 89069, exit code -11, cmd '/home/desh/yoru_ws/yoru_robot_publication/install/yoru_core/lib/yoru_core/admin_joy_node --ros-args --params-file /home/de
```
