# Simulation progress: 2026-11-19 10:53:40

**Health: PROBLEM**

- last run's real-time factor 0.168 is below 0.4

Batch runner: running for 00:21 (`--scenarios A --seed-list 0 --tag wsl_pilot_clockfix --out evaluation/data/pilot --manifest evaluation/data/pilot/manifest.csv`)
Gazebo servers: 1 (up 00:20)
Memory available: 3871 / 7795 MB, swap used 0 MB, disk free 945 GB, load 14.22
Failed attempts set aside (runs_invalid): 1

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 1 | 0 | nav2_not_ready 1 |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| baseline/L/14 | ok | admin_override | S2 | 55.0 | 60.1 | 0.916 | 2026-10-12T20:00:56 |
| baseline/L/15 | ok | admin_override | S2 | 54.7 | 60.1 | 0.911 | 2026-10-12T20:02:54 |
| baseline/L/16 | ok | admin_override | S2 | 55.0 | 60.1 | 0.916 | 2026-10-12T20:04:53 |
| baseline/L/17 | ok | admin_override | S2 | 54.7 | 60.1 | 0.911 | 2026-10-12T20:06:52 |
| baseline/L/18 | ok | admin_override | S2 | 55.0 | 60.1 | 0.916 | 2026-10-12T20:08:51 |
| baseline/L/19 | ok | admin_override | S2 | 54.5 | 60.1 | 0.907 | 2026-10-12T20:10:50 |
| baseline/K/1 | ok | safety_stop | S2 | 74.1 | 80.1 | 0.925 | 2026-10-12T20:24:21 |
| wsl_pilot_nvidia/A/0 | nav2_not_ready | none |  | 28.2 | 167.8 | 0.168 | 2026-11-19T10:44:45 |

Newest run: `evaluation/data/pilot/wsl_pilot_nvidia/A/0/run_info.json`: status nav2_not_ready, RTF 0.168, sim 28.2 s, wall 167.8 s

Newest launch log: `evaluation/data/pilot/wsl_pilot_clockfix/A/0/launch.log`
