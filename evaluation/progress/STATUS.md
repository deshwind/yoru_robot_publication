# Simulation progress: 2026-11-19 11:47:16

**Health: OK**

Batch runner: running for 30:26 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 1 (up 00:01)
Memory available: 5876 / 7795 MB, swap used 1 MB, disk free 945 GB, load 7.32
Failed attempts set aside (runs_invalid): 1

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 10 | 10 | - |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| repro_wsl/A/2 | ok | complied | S3 | 85.2 | 103.1 | 0.826 | 2026-11-19T11:22:21 |
| repro_wsl/A-V/0 | ok | complied | S3 | 85.4 | 105.1 | 0.812 | 2026-11-19T11:25:03 |
| repro_wsl/A-V/1 | ok | complied | S3 | 85.6 | 105.1 | 0.814 | 2026-11-19T11:27:47 |
| repro_wsl/A-V/2 | ok | complied | S3 | 85.5 | 104.1 | 0.821 | 2026-11-19T11:30:30 |
| repro_wsl/B/0 | ok | none |  | 120.0 | 142.2 | 0.844 | 2026-11-19T11:33:13 |
| repro_wsl/B/1 | ok | none |  | 120.0 | 168.3 | 0.713 | 2026-11-19T11:36:34 |
| repro_wsl/B/2 | ok | none |  | 120.5 | 156.3 | 0.771 | 2026-11-19T11:40:21 |
| repro_wsl/B-C7/0 | ok | logged_no_compliance | S4 | 99.7 | 140.2 | 0.711 | 2026-11-19T11:43:56 |

Newest run: `evaluation/data/repro/repro_wsl/B-C7/0/run_info.json`: status ok, RTF 0.711, sim 99.7 s, wall 140.2 s

Newest launch log: `evaluation/data/repro/repro_wsl/B-C7/1/launch.log`
