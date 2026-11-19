# Replacement machine: setup and fixes (2026-11-19)

> **Superseded:** the authoritative record, including the CPU-thread fix and every incident, is
> [`evidence/README.md`, "Replacement machine"](../../evidence/README.md#replacement-machine-2026-11-19-set-up-incidents-and-open-uncertainties).
> This file was the first working note.

The original laptop failed (broken SSD slot) after commit `f350fb4` (2026-10-15). Runs now happen on:

| | |
|---|---|
| Host | Windows, Intel i5-12500H (16 threads), 15.7 GB RAM, Intel Iris Xe + NVIDIA RTX 3050 Ti Laptop (4 GB) |
| Linux | WSL2 (WSL 3.0.5, kernel 6.18.58), Ubuntu 22.04.5, ROS 2 Humble, Gazebo 11.10.2 |
| Repository | `~/yoru_ws/yoru_robot_publication`, with `~/Yoru_bot_publication` as a symlink to it, so the absolute paths in the configuration resolve without editing tracked files (the code fingerprint is unchanged by the path) |

## Installed

- apt: `ros-humble-gazebo-ros-pkgs`, `ros-humble-gazebo-ros2-control`, `ros-humble-twist-mux`, `python3-pip`, `mesa-utils`
- pip (`--user`): `evaluation/requirements.txt` as pinned. torch 2.12.0 is the **CPU** build (`+cpu`), so YOLO runs on the CPU as in the baseline. `opencv-python-headless` 4.10.0.84 was reinstalled last so that it provides `cv2`, as on the original machine (ultralytics also pulls `opencv-python`).
- `yolov8n.pt` (ultralytics v8.4.0 asset), SHA-256 `f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36`

Checks: system tests 105 passed, evaluation tests 29 passed. `summarise.py` reproduces the committed tables and CSVs byte for byte.

## Problems found and fixed

| Problem | Effect | Fix |
|---|---|---|
| **The wall clock jumped ±21.6 s every few seconds.** Windows' clock is 21.6 s fast (it has never synced: its source is the local CMOS clock). Inside WSL, `systemd-timesyncd` kept setting the true time while WSL kept pushing the Windows time. | Gazebo's real-time pacing stalled whenever the clock jumped back; the robot spawner's 30 s timeout expired early (`Service /spawn_entity unavailable`); measured RTF 0.10 to 0.17; every pilot attempt failed with `nav2_not_ready` | `systemctl disable --now systemd-timesyncd` (Linux now follows the Windows clock). Measured with a 20 s idle + 20 s full-load probe: 5 to 8 jumps before, 0 after. Correcting the Windows clock itself requires administrator rights (Settings → Time & language → Date & time → Sync now). |
| The `sun` model was not in the local model path | Gazebo downloaded it on first start (slow first start) | Now cached in `~/.gazebo/models/sun` |
| Gazebo cameras rendered on the integrated Intel GPU by default | Slower rendering | Runs set `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` (rendering only; YOLO stays on the CPU) |
| WSL gets about 7.7 GB of RAM by default | Little headroom for Gazebo + Nav2 + 2 × YOLO | `C:\Users\User\.wslconfig`: `memory=11GB`, `swap=8GB` (takes effect after `wsl --shutdown`) |

## Known runner limitation

`run_batch.py` assumes `--out` is inside the repository: when an attempt fails, it moves the attempt to `evaluation/data/runs_invalid/<path relative to evaluation/data>` and crashes with `PermissionError` for an `--out` elsewhere. Use an `--out` under `evaluation/data/`.
