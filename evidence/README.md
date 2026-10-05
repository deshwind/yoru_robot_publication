# Evidence and results

This file collects every result and piece of evidence produced while extending the
simulation evaluation of the CCTV-triggered smoking/vaping compliance robot (ROS 2 Humble,
Gazebo classic, Nav2). Each result is traced to the file that contains it and the
script that regenerates it. Nothing in this file is estimated: values come straight from
the files listed. Where something has **not** been measured, it says so.

- Repository: `Yoru_bot_publication` (a copy of `Yoru_bot_V2` at `a7a7715`, 2026-07-30)
- Detailed audit: [`docs/sim_audit.md`](../docs/sim_audit.md)
- Scripts that produce the evidence: [`evaluation/scripts/`](../evaluation/scripts/)

| Phase | Status | Evidence folder |
|---|---|---|
| 0 Audit | done | [`phase0/`](phase0/) |
| 1 Parameterised decision rule | done | [`phase1/`](phase1/) |
| 2 Logging and instrumentation | done | [`phase2/`](phase2/) |
| 3 Human response model | done | [`phase3/`](phase3/) |
| 4 Scenarios + batch runner | done (pilot + smoke test) | [`phase4/`](phase4/) |
| 5 Metrics | tools done and validated; waiting for the baseline batch | [`phase5/`](phase5/) |
| 6 Sensitivity analysis | tool done and validated; waiting for the baseline batch | [`phase6/`](phase6/) |
| 7 Ablation | flags implemented and tested in a pending patch (applied after the batch); offline ablation done on dev data | [`phase6/`](phase6/) |

---

## Phase 0: Audit

### E0.1 Pre-existing incident logs (preserved)

The two incident logs from `~/compliance_robot_logs/` were copied into
[`phase0/incident_logs/`](phase0/incident_logs/) before any launch. The incident logger
deletes `*.jsonl` files older than 30 days on start-up, and `incidents.jsonl` was already
older than that. The copies are byte-identical (SHA-256):

| Original | Copy | SHA-256 |
|---|---|---|
| `incidents.jsonl` | `incidents_20260730.jsonl` | `53623753819fbe023102eb1670a9e0e102a194ea963c75405f65ded96b350d29` |
| `incidents.jsonl.before-demo-20260730_1410` | `incidents_before_demo_20260730_1410.jsonl` | `5d2baa53b080528a383bf97f6d76876b81c2252e726c17aac615e0473e86f91e` |

### E0.2 Logged confidence values: [`phase0/incident_summary.txt`](phase0/incident_summary.txt)

Regenerate: `python3 evaluation/scripts/phase0_incident_summary.py`

```
incident records: 337 total, 228 simulation (rooms room_a, sim_room_1)
minimum logged confidence (all records): 0.600
records with confidence < 0.600: 0

simulation records by (event_class, confidence, C5_support, fp_risk):
   228  ('cigarette', 0.802, 0.5, 'low')

simulation records by (stage_reached, outcome):
   164  ('S1', 'complied')
    28  ('S4', 'logged_no_compliance')
    21  ('S3', 'complied')
    12  ('S2', 'target_lost')
     1  ('S1', 'admin_override')
     1  ('S2', 'safety_stop')
     1  ('S2', 'admin_override')
```

**Result.** Every simulation incident ever logged has composite confidence 0.802. No incident
(simulation or real robot) has ever been logged below 0.600. Outcome counts mix several
configuration versions, so they are history and not comparable runs.

### E0.3 Composite recomputed with the real node: [`phase0/composite_recompute.txt`](phase0/composite_recompute.txt)

The live `EventConfirmationNode` callback was fed the exact detections `scenario_publisher_node`
injects. Regenerate:
`PYTHONPATH=src/yoru_core:$PYTHONPATH python3 evaluation/scripts/phase0_recompute_composites.py`

```
scenario      frame  D      P      T      S      C      C-0.3P  status
A smoking         1  0.780  0.800  0.200  0.500  0.642  0.402   uncertain
A smoking         4  0.780  0.800  0.800  0.500  0.762  0.522   uncertain
A smoking         5  0.780  0.800  1.000  0.500  0.802  0.562   confirmed
A-V vaping        5  0.780  0.800  1.000  0.200  0.772  0.532   confirmed
C target_loss     3  0.780  0.800  0.600  0.000  0.672  0.432   uncertain
C target_loss     4  0.780  0.800  0.800  0.000  0.712  0.472   uncertain
C target_loss     5  0.780  0.800  1.000  0.000  0.752  0.512   confirmed
```
(excerpt; the full frame-by-frame table is in the file)

**Result: dissertation figure.** The composite at confirmation is **0.802 (A), 0.772 (A-V)
and 0.752 (C)**, all above the 0.60 threshold. The figure's printed totals 0.56 / 0.53 / 0.47
equal **C − 0.3·P** (the composite with the proximity term left out) for A and A-V at
confirmation and for C at persistence count 4. That count is a non-confirming, *uncertain*
frame, because C4 needs 5. This explanation is **inferred from the arithmetic**: the figure's
source script was not found, so it cannot be checked directly.

**Result: what actually gates confirmation in the current sim.** Scenario A already reaches
C = 0.642 ≥ 0.60 on frame 1. With constant injected scores, the persistence criterion C4,
not the 0.60 threshold, decides when an event is confirmed.

### E0.4 Recorded demo outcome: [`phase0/DEMO_v2_reference.md`](phase0/DEMO_v2_reference.md)

A copy of V2's `docs/DEMO.md`. The recorded sim walkthrough ends with
`room_a / cigarette / stage S4 / logged_no_compliance`. This matches the code analysis
(audit §4 item 4): with `yoru_sim.yaml` the simulated person's compliance (6 s into S3)
cannot complete the 8 s reset before S3 ends at 12 s.

### E0.5 Configuration discrepancies (from the code; full table in audit §4)

| Rule | Research brief | `yoru_sim.yaml` (as run) |
|---|---|---|
| persistence before S1 | 5 s | 3 s |
| S1 PA | 3 s | 10 s |
| S2 timeout | 90 s | 60 s |
| S3 | 3 × 8 s, cap 30 s | 3 × 4 s, cap 16 s |
| compliance reset | 10 s | 8 s |
| target lost | 8 s | 5 s |

Decision (audit §8): the evaluation uses the brief's timings through a separate overlay;
`yoru_sim.yaml` is unchanged.

---

## Phase 1: Parameterised decision rule

Weights `w_D, w_P, w_T, w_S`, `confirm_confidence` and `uncertain_confidence` are ROS
parameters, settable from launch. `use_ros_clock` switches the FSM, scenario publisher and
goal sender to sim time. Every default equals the previous value.
Regenerate all Phase 1 evidence: `bash evaluation/scripts/phase1_evidence.sh`

### E1.1 Regression tests: [`phase1/pytest.txt`](phase1/pytest.txt), [`phase1/pytest_junit.xml`](phase1/pytest_junit.xml)

```
65 passed  (55 Phase 1 tests + 10 Phase 2 debug-replay tests; failures 0, errors 0, skipped 0)
```
The key test feeds the modified node and a **frozen copy of the original V2 decision code**
([`reference_event_confirmation_v2.py`](../src/yoru_core/test/reference_event_confirmation_v2.py))
the same 40 seeded random sequences of 150 frames. Every metadata message, every confirmed track and
the persistence counters are identical. A guard test confirms that these sequences really exercise the
confirmed, uncertain, phone-override and possible-vape branches. The frozen copy differs from
V2's source only in how it outputs results (checked by a line diff).

### E1.2 Mutation check: [`phase1/mutation_check.txt`](phase1/mutation_check.txt)

This checks that the tests can fail. The rule was deliberately broken in a temporary copy:

| Mutation | Test result |
|---|---|
| `w_P` 0.30 → 0.31 | 46 of 65 failed |
| `C ≥ τ` → `C > τ` | 1 of 65 failed |
| C7 gate removed | 1 of 65 failed |

### E1.3 Launch overrides: [`phase1/launch_override_check.txt`](phase1/launch_override_check.txt)

With no arguments, all 18 nodes receive exactly `[params_file, use_sim_time]`, as in V2. Given
overrides reach only the intended nodes, typed as float/bool.

---

## Phase 2: Logging and instrumentation

New topics (all `std_msgs/String` JSON, stamped with the node clock, which is sim time in Gazebo):

| Topic | Source | Content |
|---|---|---|
| `/compliance/fsm_state` | compliance_fsm_node | every transition: `stamp, previous_state, new_state, reason, track_id, room, stage_reached, direct_count, time_in_state`; plus a `cooldown_end` event |
| `/compliance/confirmation_debug` | event_confirmation_node | every tracked person, every frame (rejected included): unrounded `D, P, T, S, C`, `C1–C7`, `fp_risk_raw`, persistence count, decision, weights and thresholds in force, `stamp` (detection header) and `recv_stamp` |
| `/compliance/audio_event` | audio_warning_node | each S1/S3 warning: `stamp, kind, backend, track_id, room` |
| `/compliance/scenario_ground_truth` | scenario_publisher_node (latched) | `scenario_start`, `violation_onset`/`confounder_onset`, `comply_trigger`, `violation_cessation`, `target_removed` and a 1 Hz state heartbeat, each with scenario ID, seed and actor IDs/positions |
| `/compliance/incident_log_path` | incident_logger_node (latched) | absolute path of the run's `incidents.jsonl` |

FSM reasons: `confirmed, pa_expired, goal_reached, warnings_complete, direct_warning_cap,
approach_failed, approach_timeout, safe_stop, complied, target_lost, admin_override,
logged_no_compliance, safety_stop, cooldown_end`.

Bag recording: `ros2 launch yoru_bringup sim_full.launch.py bag_path:=<dir>` records 29 topics,
including `/gazebo/model_states` (the `gazebo_ros_state` plugin was added to the world), `/amcl_pose`,
`/scan`, `/tf`, `/plan`, Nav2 `navigate_to_pose` action status and feedback, and `/clock`. Per-run settings
go in an `overlay_params:=<yaml>` file applied after `yoru_sim.yaml`.

### E2.1 Headless check run, Scenario A: [`phase2/check_run/`](phase2/check_run/)

`bash evaluation/scripts/phase2_check_run.sh 170`. Settings: `yoru_sim.yaml` timings unchanged,
`use_ros_clock:=true`, audio playback off (events still published), e-mail off, incident log
inside the run folder ([`overlay.yaml`](phase2/check_run/overlay.yaml)). Full output:
[`bag_summary.txt`](phase2/check_run/bag_summary.txt). Bag: `phase2/check_run/bag/` (21 MB).

**Real-time factor: 160.0 s sim / 161.1 s wall = 0.993.**

FSM transitions (sim time, s):
```
t=  33.60      MONITORING -> PA_WARNING     reason=confirmed            track=c1_1001 room=room_a
t=  43.60      PA_WARNING -> APPROACH       reason=pa_expired
t=  50.50        APPROACH -> DIRECT_WARNING reason=goal_reached         (navigation 6.9 s)
t=  62.50  DIRECT_WARNING -> LOGGING        reason=warnings_complete
t=  64.60         LOGGING -> MONITORING     reason=logged_no_compliance
t= 124.60      MONITORING -> MONITORING     reason=cooldown_end         (64.6 + 60 s cooldown)
```
Ground truth: `violation_onset` 30.10, `comply_trigger` 50.50 (S3 entry), `violation_cessation` 56.50.
Audio events: PA at 33.60, direct warnings at 50.50 / 54.50 / 58.50 (3 × 4 s).
First confirmed frame: D=0.78, P=0.8, T=1.0, S=0.5, **C=0.802**, persistence 5.
Nav2: one goal to the camera spot (1.80, 0.00), `succeeded`.
Incident: `S4 / logged_no_compliance / confidence 0.802`.

**Result.** This is the first *measured* confirmation of audit §4 item 4. The simulated person
stopped at 56.5 s, but the 8 s reset would only have completed at 64.5 s, after S3 had already
ended at 62.5 s. So "complies during S3" ends as `logged_no_compliance` under `yoru_sim.yaml`.
This is why the evaluation uses the brief's timings (3 × 8 s S3, 10 s reset).

Negative control (one run only, not a rate): the room-B walking actor produced 1,595
debug records on `confirm_cctv2`, all `rejected`, with no escalation.

### E2.2 Offline replay of recorded decisions: [`phase2/replay_check.txt`](phase2/replay_check.txt)

`PYTHONPATH=src/yoru_core:$PYTHONPATH python3 evaluation/scripts/phase2_replay_check.py evidence/phase2/check_run/bag`
```
debug records replayed: 4238
exact matches (C bit-identical and same decision): 4238
mismatches: 0
header stamp -> node receive lag (s): median 0.198, min 0.000, max 3.200
```
**Result.** Every logged decision is reproduced exactly from its logged inputs, which is the
basis for the Phase 6 offline sensitivity analysis. The detection header stamp can lag
processing by up to 3.2 s (augment mode reuses the last YOLO header), so **time-based
metrics must use `recv_stamp`**, not `stamp`.

### E2.3 Behaviour unchanged

- No-argument launch: identical parameter lists for all 18 nodes (E1.3, regenerated after Phase 2).
- Regression and replay tests: 65/65 pass (E1.1).
- All instrumentation is additive (new publishers, plus a world plugin that only adds topics and services).
  The one structural change (all nodes are now created inside one `OpaqueFunction`) was checked to
  produce the same nodes, names, conditions and order as V2.

---

## Phase 3: Simulated human response model

Goal: make the simulated person behave, look and *physically exist* like a person, so that
detection, navigation and safety are exercised realistically.

### What was built

| Part | File | What it does |
|---|---|---|
| ROS-driven human actor (Gazebo plugin) | [`src/yoru_sim_plugins/src/yoru_actor_plugin.cpp`](../src/yoru_sim_plugins/src/yoru_actor_plugin.cpp) | Animated actor (walking/standing) moved from ROS (`/<actor>/cmd_pose`). Every update it moves a collision cylinder with the person, so the **lidar, costmaps and e-stop see people**. Scripted actors can do neither. |
| Evaluation world | [`src/yoru_bringup/worlds/eval_two_room.world`](../src/yoru_bringup/worlds/eval_two_room.world), generated by [`make_eval_world.py`](../evaluation/scripts/make_eval_world.py) | Demo world plus 3 people and 1 intruder (plugin-driven, with bodies). The demo world is unchanged. |
| Human actor node | [`human_actor_node.py`](../src/yoru_core/yoru_core/human_actor_node.py) | Seeded layout (start positions, which person is the violator), step-back after stopping, walking out of view (target loss), wandering bystanders, intruder crossing the robot's path |
| Detection model, `mode: world` | [`scenario_publisher_node.py`](../src/yoru_core/yoru_core/scenario_publisher_node.py) | Persons come **only from real YOLO** on the Gazebo CCTV image. Device/support detections are attached to the YOLO box of the violator, found by camera projection and IoU. One frame per YOLO frame. Compliance after a heard warning (`comply_stage` none/S1/S3_first/S3_last, `comply_delay_s`). Seeded noise. Confounders: phone, pen, straw, brief device, C7 conflict, walking. |
| Shared pure model | [`scenario_model.py`](../src/yoru_core/yoru_core/scenario_model.py) | Camera projection, seeded layout, seeded noise (separate random streams) |

Existing modes (`auto/augment/synthetic/off`) and the demo world are unchanged.
`human_actor_node` only starts with `use_actors:=true`.

### E3.1 Realistic person rendering: [`phase3/actor_render_*.png`](phase3/)

The first approach (a static mesh) rendered the skeleton's bind pose, a T-pose with the legs
below the floor. It was rejected in favour of the plugin. The three renders show the
plugin-driven actor standing (facing the camera), walking, and standing at the commanded
position (2.21, −1.18), which it reached within 0.02 m.

### E3.2 Camera projection vs YOLO: [`phase3/projection_check.txt`](phase3/projection_check.txt)

| Actor position | YOLOv8n person box | Projected box |
|---|---|---|
| (3.00, 0.30) | [358, 243, 78, 225], conf 0.90 | [360, 216, 65, 201] |
| (2.21, −1.18) | [191, 187, 67, 171], conf 0.89 | [191, 177, 54, 175] |

Horizontal centres agree within 2 px. This is how the violator is identified among several
YOLO persons; it is also encoded as a regression test.

### E3.3 Start positions

Six seeded start positions (x, y in m): (3.0, 0.3), (3.4, −1.2), (2.6, 1.4), (3.9, 0.9), (2.3, −1.5),
(3.9, −0.4). Each is fully inside the cctv1 image (≥ 20 px margin), ≥ 1.2 m from the camera spot
the robot drives to, and clear of the furniture. Two of them overlap in the image (realistic
partial occlusion), which is why matching uses IoU and not just horizontal position.

### E3.4 Unit tests: [`phase3/pytest.txt`](phase3/pytest.txt)

**81 passed** (65 earlier + 16 Phase 3). The Phase 3 tests cover:
- projection against the measured YOLO boxes;
- every start position visible and safe; exit and parking spots out of view;
- layout seeded, exactly one violator, every actor can be the violator;
- zero noise is an exact identity; seeded noise reproducible, with dropout 0.2 → measured 0.18–0.22 and σ 0.05 → measured within ±0.005;
- each `comply_stage` reacts to exactly the right warning; confounders never "comply";
- the brief device lasts 0.3 s (< 5 YOLO frames);
- the injected classes per scenario, with the C7-conflict cigarette below 0.75;
- default construction creates no world-mode state.

### E3.5 Gazebo check runs: [`phase3/runs/`](phase3/runs/) (overlays in [`phase3/overlays/`](phase3/overlays/))

All runs: evaluation world, sim time, `yoru_sim.yaml` timings, one seed each. They demonstrate the
mechanisms; they are **not** statistical results. Regenerate any run with
`bash evaluation/scripts/check_run.sh <out_dir> <overlay> <seconds>`.

| Run | Set-up | What happened (from `bag_summary.txt`) |
|---|---|---|
| **P3_A** | smoking, comply 3 s after the 1st direct warning, step back 1 m, noise σ 0.05 / dropout 10 % / bbox 3 px, seed 1 | Violator placed at (3.4, −1.2). Confirmed with D = 0.797 (noisy). S1 34.1 → S2 44.1 → S3 51.1 → **complied** 61.5. Cessation 54.1; person stepped from (3.40, −1.20) to (4.22, −1.73), 0.98 m directly away from the robot. 12 of 96 matched frames dropped. Incident `S3 / complied`. RTF 0.846. |
| **P3_JK** | 3 people (seed 2 → violator `person_2`), never complies, intruder 2 s into S2 | Only the violator was confirmed; no bystander escalated (violator matched to a YOLO box in 514 of 633 frames). Intruder crossed 2 m sideways into the path 1 m ahead of the robot (at 48.4 s); lidar min 0.303 m; **SAFE_STOP** at 48.9 s (0.4 s debounce), robot stopped at (0.94, 0.00), 0.40 m centre to centre from the person. |
| **P3_C** | cigarette, violator walks out of view 2 s into S2 | Departure 46.1 s; out of view by about 48 s. The robot reached the camera spot (51.3 s) before the 5 s target-lost window expired, so the FSM ended **`complied`** in S3. See finding 1. |
| **P3_E** | brief device (0.3 s every 6 s) + a wandering bystander | **No escalation.** 27 uncertain frames, 0 confirmed; persistence count never above 2 ([`c7_and_brief_cause.txt`](phase3/c7_and_brief_cause.txt)). 12 of those frames had C ≥ 0.60: **C4 alone prevented a false intervention.** |
| **P3_C7** | cigarette at D = 0.70 + phone at the mouth | **No escalation.** 343 frames passed C ≥ 0.6, C1, C2 and C4, and were blocked only by `fp_risk = high`: **C7 alone decided.** |
| **legacy_regression** | original demo world and mode, as Phase 2 | Same transition sequence and outcome as E2.1 (`logged_no_compliance`, C = 0.802); goal reached at 50.7 s vs 50.5 s. Existing behaviour unchanged. |

Offline replay of every Phase 3 bag ([`phase3/replay_check.txt`](phase3/replay_check.txt)): 10,953 records,
**0 mismatches**.

`P3_JK_first_attempt/` (summary only) is kept as a record of a plugin bug found and fixed. A
teleport followed immediately by a walk command lost the teleport, so the intruder walked from its
parking spot through the walls, arrived late and pushed the robot. The fix keeps a pending
teleport separately; the rerun is P3_JK.

### Findings that affect Phase 4

1. **Target loss cannot occur in S2 in the current layout.** The robot's base is at the doorway
   (0, 0) and the camera spot is 1.8 m away, so S2 lasts about 7 s. That is shorter than the 5 s
   (sim) target-lost window plus the time a departing person stays visible, and shorter than the
   brief's 8 s window. A person who leaves is then classified `complied`, because the FSM cannot
   tell absence from compliance. Proposed for Phase 4 (realism): a base farther away (room B), so
   S2 has a realistic length and navigation metrics (time, path length, replans) mean something.
2. **The real-time factor drops to 0.85–0.93 with four actors.** All decision timing now uses sim
   time, so this affects wall-clock duration, not results.
3. **Persistence is counted in real YOLO frames (about 4.6 Hz)** in world mode. Five frames are therefore
   about 1.1 s, not 0.5 s as in the legacy 10 Hz injection. This is more realistic, and must be stated in the paper.
4. **Known realism limits:** the intruder appears (teleports) 2 m beside the path before walking
   in; actors walk in straight lines without avoiding obstacles; the device itself is still an
   injected detection (no trained cigarette model runs on the Gazebo image).

---

## Phase 4: Scenario configs and batch runner

How to reproduce everything: [`evaluation/README.md`](../evaluation/README.md).

### Evaluation set-up (applies to every Phase 4+ run)

| Item | Value | Why |
|---|---|---|
| FSM timings | research brief: S0 5 s, S1 3 s, S2 ≤ 90 s, S3 3 × 8 s (cap 30 s), S4 2 s, reset 10 s, target lost 8 s, SAFE_STOP 0.35 m / 0.4 s, cooldown 60 s ([`eval_base.yaml`](../evaluation/config/eval_base.yaml)) | audit §8 Q2: gives scenarios their intended meaning (E2.1) |
| Robot base | room B (−4.0, 1.5, 0); spawn **and** AMCL initial pose ([`eval_launch.yaml`](../evaluation/config/eval_launch.yaml)) | Phase 3 finding 1: a realistic approach of about 24 s instead of about 7 s. New launch args `spawn_x/y/yaw` default to 0 (doorway, as before); checked identical by value and type. |
| Perception | real YOLOv8n persons; injected device/support with σ = 0.05, dropout 5 %, bbox jitter 3 px | realistic detector noise |
| Clock | sim time for all decision timing | ground rule 5 |
| Admin override (L) | `human_actor_node` publishes `/compliance/autonomy_paused = true`, exactly as the dashboard Pause button does | new param `admin_override_state/delay`, default off |

Scenarios ([`evaluation/scenarios/`](../evaluation/scenarios/)): A, A-V, B, **B-C7** (C7 variant,
audit §8 Q4), C, D, E, **F-pen, F-straw**, G, H, I, J, K, L. Each file records the ground truth
(violation or not) and the **expected outcome predicted from the FSM logic before any run**.
Predictions are compared with results; they are never used to tune a run.

### Batch runner: [`evaluation/scripts/run_batch.py`](../evaluation/scripts/run_batch.py)

Headless gzserver; scenarios × seeds (default 20); optional `--w-d/--w-p/--w-t/--w-s/--threshold`
(the uncertain band becomes [τ − 0.20, τ)); one bag per run under
`evaluation/data/runs/<tag>/<scenario>/<seed>/`; the run stops 10 s (sim) after the FSM outcome or at
`max_sim_s`; wall timeout; each run in its own process group and DDS domain; SIGINT → SIGTERM →
SIGKILL with a check that nothing survived; manifest CSV (scenario, seed, weights, status, outcome,
stage, outcome time, expected outcome, ground truth, wall start/end, RTF, attempts, bag check,
processes that died, code SHA-256).

**Problems the pilot exposed, and how they were fixed** (the invalid data is kept, renamed, under `evaluation/data/`):

1. `pilot_attempt1_INVALID_overlay_not_applied`: the run folder was a relative path and the launch runs
   inside it, so `overlay_params` pointed at a non-existent file, **which ROS 2 launch silently
   ignores**. The nodes ran on `yoru_sim.yaml` defaults (PA 10 s, `mode=auto`). Fixed with absolute
   paths, **plus a guard**: 20 s after start-up the runner checks that the nodes report the overlay's
   values (`mode=world`, the run's seed); otherwise the run is marked `config_not_applied` and retried.
   The same attempt also found the monitor's `/clock` subscription was RELIABLE while Gazebo publishes
   BEST_EFFORT (fixed).
2. `pilot_attempt2_stage_label_bug`: the outcome event reported `stage_reached = S0`, because the FSM
   resets the stage just before publishing. The Phase 2 instrumentation now reports the stage actually
   reached (new test `test_outcome_event_reports_the_stage_reached`; FSM behaviour unchanged; 82 tests pass).

### E4.1 Pilot: Scenario A × seeds 0–2: [`phase4/`](phase4/)

[`pilot_manifest.csv`](phase4/pilot_manifest.csv), per-seed `pilot_A_seed*_bag_summary.txt`,
`run_info.json`, and the merged overlay of seed 0. Bags in `evaluation/data/pilot/` (about 13 MB each).

| | seed 0 | seed 1 | seed 2 |
|---|---|---|---|
| status / outcome | ok / complied (S3) | ok / complied (S3) | ok / complied (S3) |
| violator start (m) | (3.9, 0.9) | (3.4, −1.2) | (3.0, 0.3) |
| violation onset → first confirmation (s) | 30.2 → 30.9 | 30.2 → 30.9 | 30.2 → 30.9 |
| first confirmed D (noisy) / C | 0.761 / 0.794 | 0.797 / 0.809 | 0.783 / 0.803 |
| S1 / S2 / S3 entry (s) | 36.1 / 39.1 / 62.9 | 36.1 / 39.1 / 63.5 | 36.1 / 39.1 / 63.1 |
| S2 duration (s) | 23.8 | 24.4 | 24.0 |
| cessation → `complied` (s) | 64.9 → 74.8 | 65.5 → 75.4 | 65.1 → 74.8 |
| dropped / matched frames | 8 / 174 | 10 / 177 | 6 / 174 |
| min robot–violator distance (m) | 2.48 | 2.20 | 1.43 |
| wall s / RTF | 96.1 / 0.893 | 96.1 / 0.894 | 95.1 / 0.898 |

Checks against the configuration: S1 starts 5.2 s after the first confirmation (5 s rule + 0.1 s tick
+ frame timing); S1 lasts exactly 3.0 s; `complied` follows cessation by 9.7–9.9 s (10 s reset, measured
from the last confirmed frame); dropout 3–6 % against the 5 % setting. These are 3 seeds: they verify
the pipeline, not the statistics.

### E4.2 Smoke test: every scenario, seed 100: [`phase4/smoke_table.md`](phase4/smoke_table.md)

Seed 100 is outside the 0–19 used for the real runs. All 15 runs `ok`, no process died, all cleaned
up; total wall time 1,550 s (about 103 s per run, so **the full 15 × 20 batch is about 9 h** and about 4 GB of bags).

| Scenario | Status | Outcome | Stage | Expected | Match | Wall s | RTF |
|---|---|---|---|---|---|---|---|
| A | ok | complied | S3 | complied | yes | 95.1 | 0.894 |
| A-V | ok | complied | S3 | complied | yes | 96.1 | 0.899 |
| B | ok | none | - | none | yes | 133.2 | 0.906 |
| B-C7 | ok | logged_no_compliance | S4 | none | **no** | 113.1 | 0.899 |
| C | ok | target_lost | S2 | target_lost | yes | 71.1 | 0.879 |
| D | ok | none | - | none | yes | 133.2 | 0.906 |
| E | ok | none | - | none | yes | 132.2 | 0.911 |
| F-pen | ok | none | - | none | yes | 133.2 | 0.907 |
| F-straw | ok | none | - | none | yes | 132.2 | 0.909 |
| G | ok | logged_no_compliance | S4 | logged_no_compliance | yes | 112.1 | 0.892 |
| H | ok | target_lost | S2 | target_lost | yes | 63.1 | 0.878 |
| I | ok | complied | S3 | complied | yes | 95.1 | 0.896 |
| J | ok | complied | S3 | complied | yes | 95.1 | 0.896 |
| K | ok | safety_stop | S2 | safety_stop | yes | 83.1 | 0.893 |
| L | ok | admin_override | S2 | admin_override | yes | 62.1 | 0.878 |

Mechanism details from the bags: **K**: intruder in the path at 59.9 s, lidar min 0.322 m, SAFE_STOP
at 60.5 s, robot–person 0.42 m (no contact). **L**: pause published 5 s into S2, FSM `admin_override`
0.1 s later. **C**: person left at 42.6 s; `target_lost` at 52.3 s (now possible thanks to the room-B
base). **H**: stopped 1 s after the PA; S1 (3 s) ended before the 10 s reset, and S2 reported
`target_lost` after 8 s, as predicted from the FSM logic. **I**: stepped back 1 m.

**Unexpected result: B-C7** ([`phase4/smoke_B-C7_cause.txt`](phase4/smoke_B-C7_cause.txt)). The cigarette
is injected at D = 0.70, below the 0.75 override. With σ = 0.05 detector noise, D exceeded 0.75 on
some frames, so the override switched C7 off. 55 frames were confirmed (D 0.750–0.836), scattered
over 34–101 s, and that was enough to escalate to S4. The FSM's 5 s rule needs a first confirmation
≥ 5 s ago and one in the last 10 s, **not continuous confirmation**. In the noise-free Phase 3 run C7
blocked everything. **Interpretation:** the single-frame override threshold makes the C7 guard
fragile under detector noise. This is a property of the system, kept as a result, and one the Phase 6
analysis can quantify.

---

## Phase 5: Metrics extraction and summary statistics

### Tools

| Script | Output |
|---|---|
| [`extract_metrics.py`](../evaluation/scripts/extract_metrics.py) (uses `rosbags` 0.11.5) | `evaluation/data/metrics.csv`, one row per run |
| [`summarise.py`](../evaluation/scripts/summarise.py) | `evaluation/results/`: `continuous.csv`, `rates.csv`, `outcomes.csv`, `tables.md`, `tables.tex` |

### Metric definitions as implemented (all times in sim seconds)

| Symbol / metric | Source |
|---|---|
| t_v | ground truth `violation_onset` |
| t_conf | first `confirmed` record on `/compliance/confirmation_debug`, by `recv_stamp` (E2.2: the header stamp can lag by up to 3.2 s) |
| t_w1 | FSM transition → PA_WARNING (S1 entry) |
| t_g / t_a | Nav2 action status: acceptance stamp of the first goal after S2 entry / first SUCCEEDED of that goal |
| t_c | first frame of the violator's camera after its last confirmed frame before t_r. If the person has left the view and no frame exists, it is the last confirmed frame + median frame interval (`t_c_source`). |
| t_r | FSM transition → MONITORING with an outcome |
| p_R, p_H | Gazebo ground truth (`/gazebo/model_states`), violator from the layout |
| confirmation_latency, detection_to_intervention, navigation_time | t_conf − t_v, t_w1 − t_conf, t_a − t_g |
| path_length | sum of ground-truth robot displacements during S2 |
| replans | two columns: `nav_recoveries` (Nav2 feedback `number_of_recoveries`) and `plan_updates` (`/plan` messages during S2; the replanning behaviour tree replans about once a second) |
| compliance_latency, violation_duration | t_c − t_w1, t_c − t_conf (`complied` runs only) |
| termination_latency | t_r − t_c, flagged when it differs by more than 0.5 s from the run's own reset (10 s) or target-lost (8 s) window, read from the run's `overlay.yaml` |
| stop_back_distance, min_distance, step_back_distance | ‖p_R(t_a) − p_H(t_a)‖; min ‖p_R − p_H‖ over S2–S3 (plus the minimum to *any* person); ‖p_H(t_c + 3 s) − p_H(t_last_warning)‖ |
| escalation_depth, warnings_delivered | highest stage 0–4; S1 + S3 audio events between t_w1 and t_r |
| outcome | complied / target_lost / logged / safety_stop / admin_override / none (`safety_stop` added: Scenario K's outcome) |
| false_intervention | violation-free run reached ≥ S1 (NaN for violation runs) |
| missed | violation run never confirmed (NaN for violation-free runs) |
| safety | `safe_stop_count`; `min_scan_range` over S2–S3 (beams > 0.2 m, as the e-stop filters the robot's own frame); `target_loss_count` |
| quality control | `cctv1_frame_hz`: effective YOLO frame rate in sim time per run (CPU load would show here); `rtf` |

Messages without a header stamp (model states, Nav2 action status, `/plan`) are placed in sim time
through the recorded `/clock` (±0.1 s). A metric that does not apply is empty, never estimated.

### E5.1 Tool validation on the pilot + smoke runs: [`phase5/tool_validation/`](phase5/tool_validation/)

These 18 runs exist only to check the tools. **They are not results** (one seed per scenario).
Extracted values were checked against independent sources:

| Check | Result |
|---|---|
| t_w1 / t_r vs `bag_summary.py` (rosbag2_py) | identical (e.g. A seed 0: 36.1 / 74.8 s) |
| t_a (from Nav2 status + clock mapping) vs FSM `goal_reached` stamp | within 0.1 s in all 8 runs where both exist |
| termination latency | 9.7–9.8 s for `complied` (window 10 s); 7.8–7.9 s for `target_lost` (window 8 s); none flagged |
| t_c vs scripted cessation | lag 0.0–0.2 s (one YOLO frame) |
| step_back_distance | I: 0.98 m (1 m scripted); A/J: 0.00 m |
| K min distance to any person | 0.419 m (bag summary 0.42 m) |
| expected-outcome match | 17/18; the mismatch is B-C7 (E4.2) |

Statistics tests ([`test_statistics.txt`](phase5/tool_validation/test_statistics.txt)): **8 passed**,
including Wilson intervals against Newcombe (1998) reference values (e.g. 81/263 →
[0.2553, 0.3662]), bootstrap reproducibility and coverage, and median/IQR against NumPy. LaTeX output is
`booktabs`, checked by eye; **it was not compiled here** (no LaTeX installation).

### E5.2 Baseline batch: running

**Infrastructure failure found during the batch: Nav2 bring-up hang.** After 21 clean runs, A-V seeds
1 and 2 ended `logged` after the 90 s S2 timeout with the robot never moving. Their logs show the Nav2
localization lifecycle manager configured AMCL but **never activated it** (no map → base_link
transform), and the navigation manager hung on "Activating planner_server". The goal sender could
therefore never send a goal. This is a Nav2 start-up race (V2's history contains a commit for a similar
bring-up abort on the real robot), not behaviour of the compliance system, so such runs are invalid
observations. Evidence: `evaluation/data/runs_invalid/`.
No foreign DDS participants were found; only the run's own process group existed.

Fix (runner only, no change under `src/`): (1) at sim 28 s, before the 30 s onset, both Nav2 lifecycle
managers must have logged "Managed nodes are active", otherwise `nav2_not_ready` and retry;
(2) `--skip-existing` re-validates earlier `ok` runs with the same check, so the two affected runs
are redone; (3) a redone run's folder is **moved** to `evaluation/data/runs_invalid/<run>__<time>__<reason>`,
never deleted; (4) the manifest stays append-only and the analysis scripts use the latest row per run.
All earlier pilot, smoke and Scenario A runs pass the check. The batch was restarted at 15:32 with
the same code fingerprint (`e76b171d83faafe5`). In the first redo, A-V seed 1 hung again on attempt 1
(caught at sim 28.2 s) and completed normally on attempt 2. The number of attempts per run is in the
manifest (`attempts`), so the infrastructure failure rate can be reported.

15 scenarios × seeds 0–19 = 300 runs, started 2026-10-05 14:30, about 110 s each (expected finish
about 23:45). Log: `evaluation/data/baseline_batch.log`; manifest: `evaluation/data/manifest.csv`.
The code fingerprint is recorded **per run**: nothing under `src/` is edited while the batch runs,
and any edit would show up as a changed `code_sha256`. Results will be added here once the batch has
finished and `extract_metrics.py` + `summarise.py` have been run.

---

## Phase 6: Event-level sensitivity analysis (offline)

### Finding that shaped the analysis: the "5 s persistence" is a delay

While reproducing the FSM logic offline, the code showed that S1 does **not** require a
confirmed event to persist for 5 s. A **single** confirmed frame starts the track's timer, and S1
fires 5 s later provided that track was confirmed within the last 10 s
(audit §4 item 10). Measured: S1 followed the first confirmed frame by 5.00–5.10 s in all 18
development runs, and the B-C7 smoke run escalated on scattered noise-driven confirmations (E4.2).
**For the paper:** the only persistence check is C4 (5 frames at frame level); the event-level
decision that triggers an intervention is "≥ 1 confirmed frame".

### Tool: [`evaluation/scripts/sensitivity_offline.py`](../evaluation/scripts/sensitivity_offline.py)

- **Events:** one per (run, camera). cctv1 takes the run's ground truth; cctv2 is always negative (room B
  never has a device). Violation events use only frames between onset and the scripted cessation.
  Confirmed = ≥ 1 confirmed frame; otherwise uncertain if any uncertain frame; otherwise rejected.
- **Recomputation:** the node's own arithmetic and gates (C ≥ τ ∧ C1 ∧ C2 ∧ C4 ∧ fp_risk ≠ high;
  uncertain band [τ − 0.20, τ)). C4 depends only on C1–C3, so the logged persistence is valid for
  every weight/threshold setting.
- **Configurations:** 4 weight sets (baseline 0.40/0.30/0.20/0.10, device-emphasis 0.50/0.25/0.15/0.10,
  persistence-emphasis 0.30/0.25/0.35/0.10, balanced 0.25 each) × τ ∈ {0.50, 0.60, 0.70}, plus
  one-at-a-time ±0.05/±0.10 on each weight with the others rescaled proportionally (16): 28 in total.
- **Per configuration:** confirmed/uncertain/rejected events, false confirmations, misses,
  precision/recall/F1, decisions changed and stability vs baseline, exact McNemar test on correctness vs
  baseline (Holm-corrected over the 27 non-baseline configurations), median confirmation latency,
  confirmed frames; plus a τ sweep 0.40–0.90 per weight set; plus the list of configurations that
  change any event decision (the candidates for Gazebo re-runs).

### E6.1 Tool validation on the 18 development runs: [`phase6/tool_validation/`](phase6/tool_validation/)

**Not results** (one seed per scenario). Required validations:

| Validation | Result |
|---|---|
| Baseline recomputation vs every logged online value | **0 / 30,610** C mismatches, **0 / 30,610** decision mismatches (bit-exact; scalar `confirmation_rule` cross-check 0 / 2,000) |
| Event decision vs the real FSM escalating | **18 / 18** runs agree |

A bug found by validation and fixed: frames are cached as 17-significant-digit CSV, but pandas'
default parser read 0.6 back as 0.5999999999999999 (1 ulp). The guard refused the cached data; it
is now read with `float_precision='round_trip'`, and the bit-exact check passes from the cache too.

What the development data already show (to be confirmed on the full set): only **balanced@0.70**
changed any decision, missing B-C7 and C. Both have no supporting evidence (S = 0), so the balanced
composite tops out around 0.63–0.65, below 0.70. Perfect event-level classification held for
τ 0.40–0.77 (baseline), 0.40–0.76 (device-emphasis), 0.40–0.80 (persistence-emphasis) and 0.40–0.65
(balanced). **No false confirmation at any τ ≥ 0.40**, because every violation-free scenario either has no
device detection (C2 fails) or is stopped by C4. Within this scenario set, weights and threshold can
therefore only cause misses, never false alarms. This is a limit of the scenario set, to be stated in the paper.

Regenerate: `python3 evaluation/scripts/sensitivity_offline.py` (full baseline, once the batch has
finished) → `evaluation/results/sensitivity/`.

### E6.2 Preview on the first 39 real baseline runs (A × 20, A-V × 19), 2026-10-05 16:30

Real noisy data, but only two scenarios, both violations: **a preview, not the result.**
Validation: 0 / 54,271 mismatches; 39 / 39 runs agree with the FSM. Findings:

- **No event decision changes** under any of the 31 settings. A sustained violation produces about
  160 confirmed frames and one is enough to escalate, so a setting must reject every frame to change
  the outcome.
- **Margins:** recall stays 1.0 up to τ = 0.81 (baseline), 0.80 (device), 0.83 (persistence),
  0.71 (balanced).
- **Frame level** (new columns `frames_changed`, `frame_stability`): persistence@0.50 changes 4,275
  frame decisions (7.9 %, all between uncertain and rejected, because the uncertain band moves with τ);
  balanced@0.70 moves 2,037 frames from confirmed to uncertain (confirmation 0.1 s later); C4 removed
  changes 158 frames (the first 4 of each violation confirm, latency 0.8 → 0.0 s); 24 settings change
  0–1 frames.
- **Structural point for the paper:** violation-free scenarios fail a hard gate (no device at the
  mouth → C2; brief device → C4), so the weights and τ cannot produce false confirmations. They
  only act on weak-evidence violations (C and B-C7 have S = 0), which the full data will cover.

### Offline ablation (Phase 7 preview), computed in the same tool

`sensitivity_offline.py` also evaluates the three Phase 7 ablations from the baseline logs, with the
same semantics as the node flags: no C4 gate (T still in the composite); C5 off (w_S = 0, the
others renormalised to 0.444/0.333/0.222); no C7 gate. Development data (18 runs, not results):

| Ablation | Event decisions changed | Effect |
|---|---|---|
| C4 off | 1 | E (brief device) becomes a **false confirmation**; violation latency drops from 0.9 s to about 0 s |
| C5 off | 0 | none |
| C7 off | 0 | none: the B-C7 run was already confirmed at baseline, because noise pushed D over the override (E4.2) |

---

## Phase 7: Ablation flags (prepared, not yet applied)

Implemented and tested in a scratch copy, **not applied to `src/`** while the baseline batch runs
(the nodes run straight from `src/`, so an edit would change the remaining runs). Stored as
[`evaluation/pending_phase7.diff`](../evaluation/pending_phase7.diff) (patched files in
`evaluation/pending_phase7_patch/`):

- `event_confirmation_node`: parameters `ablate_c4`, `ablate_c5`, `ablate_c7` (default false); the
  start-up log line reports the active ablations; debug records carry `ablations`.
- `confirmation_rule.without_support()` (C5 renormalisation).
- Launch arguments `ablate_c4/c5/c7` in `full_system`, `server` and `sim_full` (empty = off).
- `run_batch.py --ablate c4|c5|c7` (already in place, unused until the patch is applied): run-set
  tag `ablate_<c>`, manifest `ablation` column, and a guard that both confirmation nodes report the
  ablation, otherwise `config_not_applied`.
- Tests in the scratch copy: **89 passed**, the 82 existing ones (V2 equivalence included, so defaults are
  unchanged) plus 7 new ones: default off; C4 off confirms on frame 1 (C = 0.642); C5 off gives
  C = 0.836 with weights renormalised; C7 off lets the B-C7 frame through while still reporting the raw
  risk; ablated debug records replay exactly for each flag.

---

## Figures (prepared; final versions are built from the full baseline)

[`evaluation/scripts/make_figures.py`](../evaluation/scripts/make_figures.py) writes PDF + PNG to
`evaluation/results/figures/`: **fig1** outcome distribution per scenario (100 % stacked bars,
grouped by ground truth, with match counts); **fig2** median escalation timeline (stage
durations from onset, with the moment the violation ended); **fig3** timing and proximity
distributions (small multiples, runs + median, reference lines at the 8/10 s windows and the
0.35 m e-stop); **fig4** event-level precision/recall/F1 against τ for the four weight sets.
Colours are the reference palette of the dataviz guidance, used unchanged (categorical slots in
fixed order, one blue ramp for the ordered stages, grey for "no escalation"). Node.js is not
installed here, so its palette validator could not be run; only the pre-validated values are used,
within their documented series limits. Layouts were checked visually on development data (the
A/A-V baseline runs available so far plus the one-seed smoke runs); the figures in
`evaluation/data/dev/figures/` are **layout checks, not results**.

`evaluation/scripts/after_batch.sh` was started at 16:19: when the batch exits it runs
`make_results.sh` (metrics → tables → sensitivity → figures) without touching `src/`.
