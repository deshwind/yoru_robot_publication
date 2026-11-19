# Simulation progress: 2026-11-19 12:17:15

**Health: OK**

Batch runner: running for 01:00:24 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 1 (up 01:27)
Memory available: 3592 / 7795 MB, swap used 1 MB, disk free 945 GB, load 10.10
Failed attempts set aside (runs_invalid): 2

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 19 | 18 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| repro_wsl/B-C7/2 | ok | logged_no_compliance | S4 | 101.2 | 156.3 | 0.648 | 2026-11-19T11:50:52 |
| repro_wsl/C/0 | ok | target_lost | S2 | 62.3 | 92.2 | 0.676 | 2026-11-19T11:54:27 |
| repro_wsl/C/1 | ok | target_lost | S2 | 62.4 | 92.2 | 0.677 | 2026-11-19T11:56:58 |
| repro_wsl/C/2 | ok | target_lost | S2 | 64.2 | 90.1 | 0.712 | 2026-11-19T11:59:29 |
| repro_wsl/D/0 | ok | none |  | 120.6 | 154.2 | 0.782 | 2026-11-19T12:01:57 |
| repro_wsl/D/1 | ok | none |  | 120.6 | 146.2 | 0.825 | 2026-11-19T12:05:30 |
| repro_wsl/D/2 | ok | none |  | 120.1 | 147.2 | 0.816 | 2026-11-19T12:08:55 |
| repro_wsl/E/0 | ok | none |  | 120.2 | 147.2 | 0.817 | 2026-11-19T12:12:21 |

Newest run: `evaluation/data/repro/repro_wsl/E/0/run_info.json`: status ok, RTF 0.817, sim 120.2 s, wall 147.2 s

Newest launch log: `evaluation/data/repro/repro_wsl/E/1/launch.log`

```
[ERROR] [spawner-6]: process has died [pid 72119, exit code 1, cmd '/opt/ros/humble/lib/controller_manager/spawner diff_cont --ros-args'].
```
