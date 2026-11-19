# Simulation progress: 2026-11-19 11:32:16

**Health: OK**

Batch runner: running for 15:25 (`--scenarios all --seed-list 0,1,2 --tag repro_wsl --out evaluation/data/repro --manifest evaluation/data/repro/manifest.csv --skip-existing`)
Gazebo servers: 0
Memory available: 5856 / 7795 MB, swap used 1 MB, disk free 945 GB, load 14.81
Failed attempts set aside (runs_invalid): 1

## Run sets

| Manifest | rows | ok | other statuses |
|---|---|---|---|
| doc/manifest.csv | 1 | 1 | - |
| manifest.csv | 410 | 303 | actors_not_placed 1, startup_failed 106 |
| pilot/manifest.csv | 4 | 3 | nav2_not_ready 1 |
| repro/manifest.csv | 5 | 5 | - |

## Latest runs (all run sets, newest last)

| run | status | outcome | stage | sim s | wall s | RTF | start |
|---|---|---|---|---|---|---|---|
| wsl_pilot_perf/A/0 | ok | complied | S3 | 86.3 | 157.3 | 0.548 | 2026-11-19T10:58:36 |
| wsl_threads2/A/0 | ok | complied | S3 | 84.9 | 106.1 | 0.8 | 2026-11-19T11:05:54 |
| doc_pictures/A/0 | ok | complied | S3 | 85.5 | 115.2 | 0.742 | 2026-11-19T11:09:08 |
| repro_wsl/A/0 | ok | complied | S3 | 85.5 | 110.1 | 0.776 | 2026-11-19T11:16:51 |
| repro_wsl/A/1 | ok | complied | S3 | 85.2 | 102.1 | 0.834 | 2026-11-19T11:19:40 |
| repro_wsl/A/2 | ok | complied | S3 | 85.2 | 103.1 | 0.826 | 2026-11-19T11:22:21 |
| repro_wsl/A-V/0 | ok | complied | S3 | 85.4 | 105.1 | 0.812 | 2026-11-19T11:25:03 |
| repro_wsl/A-V/1 | ok | complied | S3 | 85.6 | 105.1 | 0.814 | 2026-11-19T11:27:47 |

Newest run: `evaluation/data/repro/repro_wsl/A-V/1/run_info.json`: status ok, RTF 0.814, sim 85.6 s, wall 105.1 s

Newest launch log: `evaluation/data/repro/repro_wsl/A-V/2/launch.log`

```
[admin_joy_node-26] Traceback (most recent call last):
```
