# Run recordings (compressed)

The rosbag2 recordings and run folders of every run made on the laptop since the
original baseline recordings were lost (see `evidence/README.md`, "Same laptop, new operating
system"). One deterministic `.tar.gz` per run set and scenario, made by
[`archive_recordings.py`](../scripts/archive_recordings.py); each holds the run folders
(`bag/`, `launch.log`, `overlay.yaml`, `run_info.json`, `incident_logs/`) exactly as the runner
wrote them under `evaluation/data/`. Checksums: [`CHECKSUMS.sha256`](CHECKSUMS.sha256)
(`cd evaluation/recordings && sha256sum -c CHECKSUMS.sha256`).

**Restore** (for example to re-run `extract_metrics.py` on them):

```bash
tar -xzf evaluation/recordings/repro_wsl/A.tar.gz -C evaluation/data/repro/repro_wsl
tar -xzf evaluation/recordings/aware_hold_s1/H.tar.gz -C evaluation/data/variants/aware_hold_s1
tar -xzf evaluation/recordings/misc/runs_invalid.tar.gz -C evaluation/data
tar -xzf evaluation/recordings/baseline_wsl/A/3.tar.gz -C evaluation/data/baseline_wsl/baseline_wsl
```

The baseline re-run (`baseline_wsl`) has **one archive per run** (`baseline_wsl/<scenario>/<seed>.tar.gz`,
failed attempts in `baseline_wsl/failed_attempts/`): each is written once, so git does not keep a new
copy of a growing archive after every seed. The table counts them per scenario.

| Run set | Archive | Runs (valid + failed attempts) | Raw | Compressed |
|---|---|---|---|---|
| repro_wsl | [`repro_wsl/A.tar.gz`](repro_wsl/A.tar.gz) | 3 | 40.6 MB | 7.2 MB |
| repro_wsl | [`repro_wsl/A-V.tar.gz`](repro_wsl/A-V.tar.gz) | 3 | 40.3 MB | 7.2 MB |
| repro_wsl | [`repro_wsl/B.tar.gz`](repro_wsl/B.tar.gz) | 3 | 53.6 MB | 9.1 MB |
| repro_wsl | [`repro_wsl/B-C7.tar.gz`](repro_wsl/B-C7.tar.gz) | 3 | 47.9 MB | 8.5 MB |
| repro_wsl | [`repro_wsl/C.tar.gz`](repro_wsl/C.tar.gz) | 3 | 29.0 MB | 5.2 MB |
| repro_wsl | [`repro_wsl/D.tar.gz`](repro_wsl/D.tar.gz) | 3 | 51.9 MB | 9.1 MB |
| repro_wsl | [`repro_wsl/E.tar.gz`](repro_wsl/E.tar.gz) | 3 | 52.3 MB | 9.0 MB |
| repro_wsl | [`repro_wsl/F-pen.tar.gz`](repro_wsl/F-pen.tar.gz) | 3 | 53.2 MB | 9.1 MB |
| repro_wsl | [`repro_wsl/F-straw.tar.gz`](repro_wsl/F-straw.tar.gz) | 3 | 53.1 MB | 9.1 MB |
| repro_wsl | [`repro_wsl/G.tar.gz`](repro_wsl/G.tar.gz) | 3 | 47.9 MB | 8.3 MB |
| repro_wsl | [`repro_wsl/H.tar.gz`](repro_wsl/H.tar.gz) | 3 | 25.2 MB | 4.4 MB |
| repro_wsl | [`repro_wsl/I.tar.gz`](repro_wsl/I.tar.gz) | 3 | 40.7 MB | 7.2 MB |
| repro_wsl | [`repro_wsl/J.tar.gz`](repro_wsl/J.tar.gz) | 3 | 64.6 MB | 10.6 MB |
| repro_wsl | [`repro_wsl/K.tar.gz`](repro_wsl/K.tar.gz) | 3 | 36.8 MB | 6.5 MB |
| repro_wsl | [`repro_wsl/L.tar.gz`](repro_wsl/L.tar.gz) | 3 | 25.6 MB | 4.4 MB |
| aware_hold_s1 | [`aware_hold_s1/A.tar.gz`](aware_hold_s1/A.tar.gz) | 10 | 134.1 MB | 23.9 MB |
| aware_hold_s1 | [`aware_hold_s1/C.tar.gz`](aware_hold_s1/C.tar.gz) | 10 | 95.1 MB | 17.1 MB |
| aware_hold_s1 | [`aware_hold_s1/H.tar.gz`](aware_hold_s1/H.tar.gz) | 10 | 83.7 MB | 14.4 MB |
| aware_reset_first | [`aware_reset_first/A.tar.gz`](aware_reset_first/A.tar.gz) | 10 | 132.8 MB | 23.8 MB |
| aware_reset_first | [`aware_reset_first/C.tar.gz`](aware_reset_first/C.tar.gz) | 10 | 95.0 MB | 17.0 MB |
| aware_reset_first | [`aware_reset_first/H.tar.gz`](aware_reset_first/H.tar.gz) | 10 | 86.0 MB | 15.1 MB |
| aware_both | [`aware_both/A.tar.gz`](aware_both/A.tar.gz) | 10 | 133.8 MB | 23.9 MB |
| aware_both | [`aware_both/C.tar.gz`](aware_both/C.tar.gz) | 10 | 94.8 MB | 17.1 MB |
| aware_both | [`aware_both/H.tar.gz`](aware_both/H.tar.gz) | 10 | 83.3 MB | 14.4 MB |
| misc | [`misc/pilot.tar.gz`](misc/pilot.tar.gz) | 4 | 48.0 MB | 8.5 MB |
| misc | [`misc/doc.tar.gz`](misc/doc.tar.gz) | 1 | 14.3 MB | 2.4 MB |
| misc | [`misc/phase_b.tar.gz`](misc/phase_b.tar.gz) | 1 | 24.4 MB | 4.3 MB |
| misc | [`misc/runs_invalid.tar.gz`](misc/runs_invalid.tar.gz) | 21 | 75.6 MB | 12.6 MB |
| baseline_wsl | [`baseline_wsl/A`](baseline_wsl/A) | 1 | 13.5 MB | 2.4 MB |
| baseline_wsl | [`baseline_wsl/A-V`](baseline_wsl/A-V) | 1 | 13.5 MB | 2.4 MB |
| baseline_wsl | [`baseline_wsl/B`](baseline_wsl/B) | 1 | 17.9 MB | 3.1 MB |
| baseline_wsl | [`baseline_wsl/B-C7`](baseline_wsl/B-C7) | 1 | 16.0 MB | 2.8 MB |
| baseline_wsl | [`baseline_wsl/C`](baseline_wsl/C) | 1 | 9.4 MB | 1.7 MB |
| baseline_wsl | [`baseline_wsl/D`](baseline_wsl/D) | 1 | 17.1 MB | 3.0 MB |
| baseline_wsl | [`baseline_wsl/E`](baseline_wsl/E) | 1 | 17.1 MB | 3.0 MB |
| baseline_wsl | [`baseline_wsl/F-pen`](baseline_wsl/F-pen) | 1 | 17.8 MB | 3.0 MB |
| baseline_wsl | [`baseline_wsl/F-straw`](baseline_wsl/F-straw) | 1 | 17.8 MB | 3.0 MB |
| baseline_wsl | [`baseline_wsl/G`](baseline_wsl/G) | 1 | 16.2 MB | 2.9 MB |
| baseline_wsl | [`baseline_wsl/H`](baseline_wsl/H) | 1 | 8.5 MB | 1.5 MB |
| baseline_wsl | [`baseline_wsl/I`](baseline_wsl/I) | 1 | 13.7 MB | 2.4 MB |
| baseline_wsl | [`baseline_wsl/J`](baseline_wsl/J) | 1 | 33.9 MB | 5.5 MB |
| baseline_wsl | [`baseline_wsl/K`](baseline_wsl/K) | 1 | 12.2 MB | 2.2 MB |
| baseline_wsl | [`baseline_wsl/L`](baseline_wsl/L) | 1 | 8.7 MB | 1.5 MB |
| baseline_wsl | [`baseline_wsl/failed_attempts/A`](baseline_wsl/failed_attempts/A) | 1 | 4.1 MB | 0.7 MB |

Total: 178 run folders, 2001 MB raw, 350 MB compressed.

Run sets: `repro_wsl` = the 45-run reproduction (scenarios × seeds 0–2); `aware_*` = Phase C
FSM-variant sets; `baseline_wsl` = the baseline re-run (seeds 3–19); `misc` = pilot and
diagnostic runs (`pilot`), the documentation run (`doc`), the Phase B check run (`phase_b`)
and every failed attempt set aside by the runner (`runs_invalid`).
