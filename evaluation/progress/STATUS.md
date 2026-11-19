# Simulation progress: 2026-11-19 11:06:35

**Health: OK**

Batch runner: running for 00:41 (`--scenarios A --seed-list 0 --tag wsl_threads2 --out evaluation/data/pilot --manifest evaluation/data/pilot/manifest.csv`)
Gazebo servers: 1 (up 00:40)
Memory available: 3714 / 7795 MB, swap used 1 MB, disk free 945 GB, load 12.33
Failed attempts set aside (runs_invalid): 1

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 3 | 2 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| baseline/L/16 | ok | admin_override | S2 | 55.0 | 60.1 | 0.916 | 2026-10-12T20:04:53 |
| baseline/L/17 | ok | admin_override | S2 | 54.7 | 60.1 | 0.911 | 2026-10-12T20:06:52 |
| baseline/L/18 | ok | admin_override | S2 | 55.0 | 60.1 | 0.916 | 2026-10-12T20:08:51 |
| baseline/L/19 | ok | admin_override | S2 | 54.5 | 60.1 | 0.907 | 2026-10-12T20:10:50 |
| baseline/K/1 | ok | safety_stop | S2 | 74.1 | 80.1 | 0.925 | 2026-10-12T20:24:21 |
| wsl_pilot_nvidia/A/0 | nav2_not_ready | none |  | 28.2 | 167.8 | 0.168 | 2026-11-19T10:44:45 |
| wsl_pilot_clockfix/A/0 | ok | complied | S3 | 86.7 | 152.2 | 0.57 | 2026-11-19T10:53:19 |
| wsl_pilot_perf/A/0 | ok | complied | S3 | 86.3 | 157.3 | 0.548 | 2026-11-19T10:58:36 |

Newest run: `evaluation/data/pilot/wsl_pilot_perf/A/0/run_info.json`: status ok, RTF 0.548, sim 86.3 s, wall 157.3 s

Newest launch log: `evaluation/data/pilot/wsl_threads2/A/0/launch.log`
