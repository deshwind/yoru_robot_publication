# Simulation audit (Phase 0)

Audit of the simulation pipeline in `Yoru_bot_publication`, a copy of `Yoru_bot_V2`
(HEAD `a7a7715`, 2026-07-30). No behaviour has been changed. Every claim below is
taken from the code (file and line references are into this repository) or from
the incident logs in `~/compliance_robot_logs/`. Anything that has not been
measured is marked **not verified**.

Changes made while copying V2 (path edits only, behaviour unchanged):
`Yoru_bot_V2` → `Yoru_bot_publication` in `src/yoru_bringup/config/yoru_sim.yaml`,
`src/yoru_bringup/launch/sim.launch.py` and `src/yoru_bringup/launch/sim_full.launch.py`,
so the copy reads its own maps and model files. The real-robot config, Pi scripts and
node defaults (`audio_warning_node` voice path, `dashboard_node`, `map_reset_node`,
`camera_target_node`) still reference `~/Yoru_bot_V2`.

---

## 1. Repository map

### Packages

| Package | Type | Contents |
|---|---|---|
| `yoru_base` | ament_cmake | Robot URDF/xacro, ros2_control, Gazebo worlds, Nav2 / slam_toolbox / AMCL configs and launch files |
| `yoru_bringup` | ament_cmake | System launch files, `yoru_sim.yaml` / `yoru_real.yaml`, two-room sim world, RViz config |
| `yoru_core` | ament_python | All compliance nodes (18 executables), training tools, audio files |

### Simulation launch tree (`./start_sim.sh` → `sim_full.launch.py`)

```
sim_full.launch.py  (args: mode, map, gui, rviz, open_browser, use_joystick)
├── sim.launch.py   (robot side; use_sim_time hard-coded true)
│   ├── rsp.launch.py, gazebo_ros gazebo.launch.py (world = two_room_world.world)
│   ├── spawn_entity, diff_cont + joint_broad spawners, twist_mux
│   ├── [t+5 s] localization_launch.py (AMCL + map_server) if maps/sim/main_map.yaml exists,
│   │           else online_async_launch.py (slam_toolbox)            ← mode:=auto
│   ├── [t+8 s] navigation_launch.py (Nav2, nav2_params.yaml)
│   └── static TFs cctv1_tf / cctv2_tf, [t+6 s] rviz2
└── server.launch.py sim:=true
    ├── full_system.launch.py (params_file=yoru_sim.yaml, use_sim_time=true,
    │                          use_scenario=true, use_cctv2=true)
    └── joystick.launch.py, dashboard browser opener
```

`maps/sim/main_map.yaml` exists, so `mode:=auto` resolves to **localization (AMCL)**.

### Nodes started by `full_system.launch.py` in simulation

| Node name (param key) | Executable | Subscribes | Publishes |
|---|---|---|---|
| `yolo_cctv1` | yolo_detector_node | `/cctv1/image_raw` | `/compliance/cctv1/detections_yolo`, `/compliance/cctv1/debug_image[/compressed]`, `/compliance/smoking_detected` |
| `scenario_publisher_node` | scenario_publisher_node | `/compliance/cctv1/detections_yolo`, `/compliance/fsm_status` | `/compliance/cctv1/detections` |
| `tracking_cctv1` | tracking_node | `/compliance/cctv1/detections` | `/compliance/cctv1/tracked`, `/compliance/tracking_info` |
| `confirm_cctv1` | event_confirmation_node | `/compliance/cctv1/tracked` | `/compliance/cctv1/confirmed`, `/compliance/event_metadata` |
| `camera_target_cctv1` | camera_target_node | `/compliance/cctv1/confirmed` | `/compliance/navigation_targets`, `/compliance/target_marker` |
| `yolo_cctv2`, `tracking_cctv2`, `confirm_cctv2`, `camera_target_cctv2` | as above | `/cctv2/...`; YOLO output goes **straight to tracking** (no scenario injection) | `/compliance/cctv2/...` |
| `nav2_goal_sender_node` | | `/compliance/navigation_targets`, `/compliance/fsm_status` | `/compliance/nav_status`; action client `navigate_to_pose` |
| `compliance_fsm_node` | | `/compliance/cctv{1,2}/confirmed`, `/compliance/event_metadata`, `/compliance/nav_status`, `/scan`, `/compliance/autonomy_paused` | `/compliance/fsm_status`, `/compliance/pa_warning`, `/compliance/direct_warning`, `/compliance/incident_log`, `cmd_vel_tracker` |
| `audio_warning_node` | | `/compliance/pa_warning`, `/compliance/direct_warning` | (none; plays audio and logs `[PA_WARNING]` / `[DIRECT_WARNING]`) |
| `incident_logger_node` | | `/compliance/incident_log`, `/compliance/navigation_targets` | writes `~/compliance_robot_logs/incidents.jsonl` |
| `incident_emailer_node` | | `/compliance/incident_log`, `/compliance/fsm_status`, camera topics | email (needs `COMPLIANCE_EMAIL_PASSWORD`) |
| `patrol_node` | | `/compliance/fsm_status`, `/compliance/base_request`, `/compliance/autonomy_paused` | `enabled: false` in sim |
| `return_to_base_node` | | battery / manual request / fsm_status | only on low battery or manual request (does **not** return after an escalation) |
| `admin_joy_node`, `dashboard_node` | | `/joy`, … | `/compliance/autonomy_paused` (admin override), `/compliance/pa_warning` (manual PA), `cmd_vel_tracker`, `/initialpose` |

### Message types on the decision path

| Topic | Type | Payload |
|---|---|---|
| `/compliance/cctvN/detections[_yolo]`, `/tracked`, `/confirmed` | `vision_msgs/Detection2DArray` | `results[0].hypothesis.class_id/score`, bbox in pixels, `det.id` = track ID (after tracking) |
| `/compliance/event_metadata` | `std_msgs/String` (JSON) | per person and frame, **only if status ≠ rejected**: `track_id, room, status, confidence, event_class, criteria{C1..C7}, scores{device, proximity, persistence, support}`; also `possible_vape` hints |
| `/compliance/fsm_status` | `std_msgs/String` (JSON) | `state, track_id, room, elapsed, stage_reached`; sent on every transition and about once a second as a heartbeat |
| `/compliance/pa_warning`, `/compliance/direct_warning` | `std_msgs/String` (JSON) | `message, track_id, room, event_class` |
| `/compliance/nav_status` | `std_msgs/String` (JSON) | `state` ∈ navigating, succeeded, cancelled, aborted, timeout, rejected, nav2_unavailable |
| `/compliance/incident_log` | `std_msgs/String` (JSON) | `track_id, room, event_class, stage_reached, outcome, confidence, criteria` |
| `/compliance/navigation_targets` | `geometry_msgs/PoseStamped` | camera spot from `maps/sim/cameras.json` (cctv1 → x=1.8, y=0.0, yaw=0) |
| `/compliance/autonomy_paused` | `std_msgs/Bool` | admin override |

---

## 2. `event_confirmation_node.py`: exact computation

The node is called once per incoming `Detection2DArray`. The rate is set by the upstream
publisher: **10 Hz on cctv1** (scenario publisher `publish_hz`) and up to
**5 Hz on cctv2** (YOLO `process_hz`). It runs the following for every `person`
detection in the frame (`event_confirmation_node.py:121`).

### Class buckets (lines 26–28, 103–115)
- devices: `cigarette`, `vape_device`
- support: `smoke_vapour` (0.3), `hand_mouth_gesture` (0.2), `hand_face` (0.1)
- confounders: `pen`, `mobile_phone`, `straw`. In COCO mode `yolo_detector_node`
  maps `cell phone`/`remote` → `mobile_phone`, `toothbrush`/`fork` → `pen`, and
  `cup`/`bottle` → `straw` (`yolo_detector_node.py:33-40`).

### The four scores

| Score | Code | Range / normalisation |
|---|---|---|
| **D** (device) | `device_score = best_device.score if c2 else 0.0` (l.170) | Raw detector score. **No further normalisation.** In simulation the injected device always has score 0.78. |
| **P** (proximity) | `prox = max(min(IoU/0.3, 1.0), 0.8 if near_mouth else 0.0)` (l.134), best over devices | IoU between the **whole person box** and the device box, scaled so IoU 0.3 → 1.0, with a floor of **0.8** if the device centre is in the mouth region: within ±0.75·w of the person's centre x and in the top 40 % of the box (`in_mouth_region`, l.47). In practice it is almost always exactly 0.8, because a small device box has a tiny IoU with a person box (0.029 in sim). |
| **T** (persistence) | `min(frames / persistence_frames, 1.0)` (l.150) | `frames` is a per-track **leaky counter**: +1 when C1∧C2∧C3 hold, otherwise −1 (floor 0) (l.143-147). It is not a strict consecutive count (V1 in `dock_ws` reset it to 0; V2 commit `e53f612` changed that). |
| **S** (support) | Sum of support weights for support boxes in the top 60 % of the person box or with IoU > 0.02, capped at 1.0 (l.153-158) | Reachable maximum is **0.6** (0.3 + 0.2 + 0.1), so S never reaches 1. |

**Composite** (l.171): `C = 0.4·D + 0.3·P + 0.2·T + 0.1·S`, with the weights **hard-coded**
in the expression. Weights cannot currently be changed without editing code.

### C1–C7

| Criterion | Evaluation | Used as a gate? |
|---|---|---|
| C1 person | `person.score > person_confidence` (strict `>`; default 0.7) | **Yes** |
| C2 device | a device with `score > device_confidence` (strict; 0.6) **and** (IoU > `proximity_iou` (0.05) **or** in mouth region) | **Yes**. Note that C2 already includes the proximity test |
| C3 proximity | `best_prox > 0` | Not separately: it is implied by C2 (C2 ⇒ C3) |
| C4 persistence | `frames >= persistence_frames` (5) | **Yes** |
| C5 support | S score | No (weight only) |
| C6 track | `track_id != 'untracked'` | No (reported only; persistence is keyed by track ID) |
| C7 fp_risk | `'high'` if **any** confounder's centre is in the mouth region (first match, `break`) | **Yes** (`fp_risk != 'high'`) |
| C7 override | if `fp_risk=='high'` and C2 and `D >= confounder_override_confidence` (0.75) then `'overridden'` | the override un-blocks the gate |

### Decision (l.182-206)

```
confirmed = C >= confirm_confidence(0.6) AND C1 AND C2 AND C4 AND fp_risk != 'high'
status    = 'confirmed' if confirmed else 'uncertain' if C >= uncertain_confidence(0.4) else 'rejected'
```

- Confirmed: the person detection (with track ID) is appended to `/compliance/cctvN/confirmed`.
- Confirmed **and** uncertain frames are published as JSON on `/compliance/event_metadata`.
  **Rejected frames are not published anywhere**, so they cannot currently be analysed offline (Phase 2b fixes this).
- The uncertain lower bound is a separate parameter (`uncertain_confidence` 0.4). It is not computed as `threshold − 0.20`.
- Persistence state for tracks absent from the current frame is deleted (l.237).

### Where the numbers are defined

| Value | Location |
|---|---|
| weights 0.4/0.3/0.2/0.1 | hard-coded, `event_confirmation_node.py:171` |
| P scale (IoU/0.3) and floor 0.8 | hard-coded, l.134 |
| mouth region 0.4 (device/confounder), 0.6 (support), x ±0.75·w | hard-coded, l.47, 155 |
| support weights | hard-coded `SUPPORT_WEIGHTS`, l.27 |
| `person_confidence`, `device_confidence`, `proximity_iou`, `persistence_frames`, `confirm_confidence`, `uncertain_confidence` | ROS params (l.63-68); set in `yoru_sim.yaml` under `confirm_cctv1/2` (same values as the defaults) |
| `confounder_override_confidence` 0.75, `vape_hint` | ROS params (l.75, 80) |

---

## 3. The dissertation figure inconsistency

### What the code produces

With the scenario publisher's injected values (D=0.78, device in the mouth region ⇒ P=0.8)
I evaluated the node's own `bbox_iou`/`in_mouth_region` functions for the sim geometry
(person 320,240,60×150 px) and for the node-default geometry (320,300,80×200). Both give identical scores:

| Scenario | S (support boxes injected) | C at counter = 1…5 | C when confirmed (T=1) |
|---|---|---|---|
| A smoking | 0.5 (hand_mouth 0.2 + smoke 0.3) | 0.642, 0.682, 0.722, 0.762, **0.802** | **0.802** |
| A-V vaping | 0.2 (hand_mouth only) | 0.612, 0.652, 0.692, 0.732, **0.772** | **0.772** |
| C target_loss (cigarette) | 0.0 (no support injected) | 0.592, 0.632, 0.672, 0.712, **0.752** | **0.752** |

Term contributions at confirmation: 0.4·D = 0.312, 0.3·P = 0.240, 0.2·T = 0.200, 0.1·S = 0.050 / 0.020 / 0.000.

**Logged evidence.** All 228 simulation incidents in `~/compliance_robot_logs/` (rooms `room_a` and
`sim_room_1`, June–July 2026) record `confidence: 0.802` with `C5_support: 0.5`. Every one of the 337
logged incidents (sim and real) has confidence ≥ 0.600. This follows from the code: the incident's
`confidence` is copied from the target's last **confirmed** metadata (`compliance_fsm_node.py:134-135, 242`),
and a confirmed frame must have C ≥ 0.6 and T = 1.0. No vaping or target-loss incidents
with sim room names are in the log, so the A-V and C values above are computed, not logged.

### Which values are correct

- **Correct:** the bar heights (≈0.80, ≈0.75, ≈0.70). The composite at confirmation is 0.802 / 0.772 / 0.752, all above 0.60.
- **Incorrect:** the printed totals 0.56, 0.53, 0.47. They cannot be confirmed-event composites, because the
  code never confirms below 0.60.

### Most likely cause (inferred from arithmetic, not verified against the figure script)

All three printed totals equal **the composite minus the proximity term (0.3·P = 0.24)**:

| | Composite | − 0.24 | Printed |
|---|---|---|---|
| A (T=1.0) | 0.802 | 0.562 | 0.56 |
| A-V (T=1.0) | 0.772 | 0.532 | 0.53 |
| C (counter = 4, T = 0.8) | 0.712 | 0.472 | 0.47 |

So the figure script most probably left the P term out when it summed the total, while still drawing the P bar.

**Scenario C's T.** A T below 1 means the leaky counter was below 5, so **C4 was false on that
frame and the frame was 'uncertain', not confirmed.** The C bar therefore came from an
`/compliance/event_metadata` message published during the ramp-up (or during decay after the
target vanished), not from the confirming frame. The arithmetic fits counter = 4 (T=0.8,
bar sum 0.712 ≈ 0.70, total−P = 0.472). Your reading of T ≈ 0.6 would be counter = 3, which gives a bar sum of 0.672
and total−P of 0.432. I can't tell these apart without the figure source. In either case the frame is not a confirming frame.

**What I could not check:** the figure's source script or data. I found no plotting script in
`Yoru_bot_V2`, `dock_ws` or `~/dissertation (1)`. If you can supply it, this section can be confirmed or corrected.

**Note for the paper.** Because the synthetic scores are constant, the composite already reaches
0.642 (smoking) on the **first** frame. In the current sim, the decision that actually gates is C4, not the
0.60 threshold. Phase 6 sensitivity results will be nearly degenerate unless the Phase 3 detection noise is used.

---

## 4. FSM: actual behaviour vs the research brief

All FSM timing uses **`time.monotonic()` (wall clock)**. See §6.

### Parameters

| Rule | Brief | Code default (`compliance_fsm_node.py`) | `yoru_sim.yaml` (what sim runs) |
|---|---|---|---|
| S0 persistence before S1 (`monitor_confirm_duration`) | 5 s | 3.0 | 3.0 |
| S1 PA (`pa_warning_duration`) | 3 s | 15.0 | 10.0 (`yoru_real.yaml`: 0.0) |
| S2 timeout (`approach_timeout`) | 90 s | 60.0 | 60.0 (+ goal sender `goal_timeout` 60) |
| S3 warnings (`direct_warning_repeats` × `interval`, cap `direct_warning_duration`) | 3 × 8 s, cap 30 s | 3 × 8 s, cap **15 s** | 3 × 4 s, cap 16 s |
| S4 (`logging_duration`) | n/a | 2.0 | 2.0 |
| Cooldown | 60 s | 60.0 | 60.0 |
| Compliance reset (`compliance_clear_duration`) | > 10 s | 10.0 | **8.0** |
| Obstacle stop | < 0.35 m for 0.4 s | 0.35 m, 0.4 s debounce, ≥ 4 beams, ±60° front cone, ignore < 0.2 m | 0.35 (others default) |
| Target lost (`target_lost_timeout`) | > 8 s | 5.0 | 5.0 |
| SAFE_STOP hold (`safe_stop_duration`) | n/a | 3.0 | 3.0 |

### Transitions as implemented (`tick()` at 10 Hz, l.276)

Checks run in this priority order on every tick:

1. **Admin override.** If `/compliance/autonomy_paused` is true and state ≠ MONITORING, then `finish_escalation('admin_override')`.
2. **Compliance reset.** In PA_WARNING, APPROACH or DIRECT_WARNING, if the target has no confirmed evidence
   (its own track **or any confirmed metadata from the same room**) for ≥ `compliance_clear_duration`, then `'complied'`.
3. Per-state logic:

| From | Condition | To | `stage_reached` / outcome |
|---|---|---|---|
| MONITORING | a track (or its room) has been confirmed for ≥ `monitor_confirm_duration` and is not in cooldown | PA_WARNING (PA published) | S1 |
| PA_WARNING | elapsed ≥ `pa_warning_duration` | APPROACH | S2 |
| APPROACH | ≥ 4 forward beams < 0.35 m for ≥ 0.4 s | SAFE_STOP | |
| APPROACH | target lost > `target_lost_timeout` | MONITORING | outcome `target_lost` |
| APPROACH | nav `succeeded` | DIRECT_WARNING (warning 1 published) | S3 |
| APPROACH | nav aborted/timeout/rejected/nav2_unavailable, or elapsed ≥ `approach_timeout` | LOGGING | S4 |
| DIRECT_WARNING | every `interval`: send the next warning; once `repeats` are sent and another interval passes, or the cap is reached | LOGGING | S4 |
| LOGGING | elapsed ≥ 2 s | MONITORING | outcome `logged_no_compliance` |
| SAFE_STOP | publishes zero Twist each tick; elapsed ≥ 3 s | MONITORING | outcome `safety_stop` (escalation **ends**; it does not resume) |

### Behaviours that differ from the brief or matter for the evaluation

1. **"Complied" does write an incident record.** `finish_escalation()` always calls
   `log_incident()` (l.250), so `complied`, `target_lost`, `safety_stop` and `admin_override` are all written
   to `incidents.jsonl`, together with `stage_reached`. The brief says complied → "no S4 record". That holds
   only in the sense that `stage_reached` will not be S4.
2. **Target loss is checked only in APPROACH.** In PA_WARNING and DIRECT_WARNING a vanished target ends as
   `complied` after `compliance_clear_duration`.
3. **Compliance during S2 is classified as `target_lost`, not `complied`.** In the sim config the
   target-lost timeout (5 s) is shorter than the clear duration (8 s). Scenario H ("complies during S1")
   ends as `complied` only if the reset completes before the 10 s PA window ends. Otherwise it moves to
   APPROACH and becomes `target_lost`.
4. **Scenario A with `yoru_sim.yaml` ends in S4, not complied.** The scenario publisher removes the
   device 6 s after DIRECT_WARNING starts. Warnings fire at t = 0, 4, 8 s and LOGGING starts at t = 12 s.
   The reset would need 6 + 8 = 14 s. `docs/DEMO.md` records exactly this outcome
   (`stage S4 / logged_no_compliance`). Logged simulation history (rooms `room_a`/`sim_room_1`, 228 records):
   164 × S1 complied, 28 × S4 logged_no_compliance, 21 × S3 complied, 12 × S2 target_lost, 1 × S2 safety_stop,
   2 × admin_override (`evidence/phase0/incident_summary.txt`). These come from several config versions, so they are not
   comparable runs. *(Corrected 2026-10-05: an earlier version of this audit quoted the counts for all 337 records, real robot included, as simulation counts.)*
5. **With code defaults only 2 direct warnings are delivered.** 3 × 8 s needs 24 s but the cap is 15 s
   (warnings at 0 s and 8 s, then LOGGING at 15 s). The sim config avoids this (3 × 4 s, cap 16 s).
6. **Cooldown is per track ID, not per person or room.** A new track ID in the same room is not in
   cooldown, and it inherits the room's `room_first_seen` (l.345-349). So it can trigger a new S1
   immediately after a finished escalation, if the room has stayed active.
7. **There is no `cooldown_end` transition.** Cooldown is a dictionary lookup in MONITORING, not a state.
   Likewise `confirmed`, `pa_expired` and `goal_reached` are not explicit reasons today. Phase 2a will add them as labels.
8. **The robot does not return to base after an escalation.** `return_to_base_node` acts only on low battery or a manual
   request. Each batch run therefore needs a fresh Gazebo world (or an explicit reset).
9. `/compliance/fsm_status` is also a ~1 Hz heartbeat, so transitions cannot be detected from it by
   message count alone. You have to watch for a change in `state`.
10. **The "5 s persistence before S1" is a delay, not a persistence requirement** (added 2026-10-05
    during Phase 6). `events_callback` stores a track's first confirmed time, and `monitoring_tick`
    escalates once `now − first ≥ monitor_confirm_duration` *while the track is not stale*, meaning its last
    confirmed frame is within `compliance_clear_duration` (10 s). A **single** confirmed frame therefore
    triggers S1 exactly 5 s later; confirmations in between are not required. The data agree:
    detection-to-intervention is 5.0–5.1 s in every escalated run, and in the B-C7 smoke run scattered
    noise-driven confirmations escalated (evidence E4.2). Consequence: the event-level decision that
    matters is "≥ 1 confirmed frame", and C4 (5 frames of *frame-level* persistence) is the only
    persistence check in the pipeline.

---

## 5. `scenario_publisher_node.py`: how detections are injected

**Only cctv1 (room A) is injected.** cctv2's YOLO output goes straight to tracking, so
room B (the walking actor) is a real-YOLO, no-device negative control.

Timer at `publish_hz` (10 Hz). Each tick (l.118):

1. `mode == off` → nothing is published.
2. **Person source.**
   - `augment` / `auto` with a YOLO message < 1 s old: forward **all** YOLO detections, and use the first YOLO person box.
   - otherwise, if a real person box is < `coast_duration` (3 s) old: re-publish it as a `person` at score **0.85**.
   - otherwise (`synthetic`, or `auto` without YOLO): a synthetic `person` at score **0.92**, at
     (`person_pixel_x`, `person_pixel_y`, `person_bbox_w`, `person_bbox_h`). The sim uses (320, 240, 60, 150).
   - `augment` with no YOLO person: pass-through, with no device.
3. **Violation.** Once `elapsed ≥ start_delay` (sim 30 s; default 20 s) and the actor has not complied, it adds:
   - the device at **score 0.78**, box 22×12 px, centre (mouth_x + 8, top + 0.18·h). The class is
     `cigarette`, `vape_device` (scenario `vaping`) or `mobile_phone` (`false_positive`);
   - smoking/vaping: `hand_mouth_gesture` 0.70, 50×40 at the mouth;
   - smoking only: `smoke_vapour` 0.60, 60×50 at (mouth_x + 25, mouth_y − 30).
4. **Compliance.** The node watches `/compliance/fsm_status`. The first time `state == comply_after_stage`
   (sim: `DIRECT_WARNING`) it starts a timer. After `comply_delay` (sim 6 s) it sets `complied = True` and the
   device and support boxes stop permanently. The person stays.
5. **Target loss** (`scenario_type: target_loss`). From `start_delay + target_loss_after` (default 30 s,
   not set in sim yaml) the node publishes **nothing** (person included), permanently. This is timed from
   scenario start, **not from an FSM stage**, so "target disappears during S2" is not guaranteed. It depends on how long
   S0+S1 (3 + 10 s) and navigation take. **Not verified** in a run.

### Gaps that matter for the planned evaluation

- **Wall-clock timing** (`time.monotonic()`) for start delay, compliance delay and target loss.
- **No seed and no randomness.** Scores and boxes are constant, and no noise or dropout model exists.
- **No ground-truth output.** Onset and cessation times exist only as internal variables and log lines.
- **Scenario B does not exercise C7.** It injects only a `mobile_phone`, so C2 is false and the person is
  rejected with C = 0 (T never grows), whatever C7 says. C7 only matters when a real device **and** a
  confounder are both at the mouth with D < 0.75. The injected D = 0.78 ≥ 0.75 would trigger the
  override, so even a mixed injection would be confirmed. Scenario B also triggers the dashboard-only
  `possible_vape` hint after 5 frames.
- **The Gazebo actors don't move with the violation.** `person_smoking` is a scripted *standing* actor at (3.0, 0.3)
  and `person_walking` is a looping scripted walker. Compliance is simulated only by removing detections.
  The actor never moves.
- Only one injected person, so there is no multi-person or confounder geometry yet.

---

## 6. Timing and sim time (conflict with ground rule 5)

`use_sim_time:=true` is passed to every node, but it only affects `self.get_clock()`. Header stamps and
the goal stamp therefore use sim time. **Every duration in the decision logic uses wall-clock
`time.monotonic()`:** the whole FSM (states, confirm window, clear window, target loss, debounce),
the scenario publisher (start delay, compliance delay, target loss, YOLO freshness, coast),
`nav2_goal_sender_node` (goal cooldown/timeout, target age) and the tracking latency. The incident
logger timestamps with `datetime.now()`.

Consequence: whenever Gazebo's real-time factor is below 1 (likely with two YOLO pipelines, Nav2 and
rendering all on one machine), every FSM duration lasts **fewer simulated seconds** than its nominal value.
Latencies measured from bag stamps (sim time) will not equal the configured windows. For example, the
"termination latency ≈ 10 s" check in Phase 5 would show RTF·8 s. **The RTF has not been measured.**

Switching these to `self.get_clock()` would make the logic follow sim time, but it **changes behaviour**
(ground rule 2). This needs your decision (see §8).

---

## 7. Other findings relevant to Phases 2–7

| Area | Finding | Impact |
|---|---|---|
| Gazebo model states | `two_room_world.world` loads no `libgazebo_ros_state.so`, so `/gazebo/model_states` is not published | Phase 2e has to add the plugin (or get poses another way) |
| Actors and lidar | Actors are scripted and have no collision geometry. The robot lidar is a CPU `ray` sensor (`lidar.xacro:40`) | Gazebo-classic actors are generally **invisible to CPU ray sensors**. Scenario K (a person crossing the path → SAFE_STOP) would need a collidable moving *model*, not an actor. **Not verified** |
| Moving actors | Scripted-trajectory actors ignore `set_entity_state` in Gazebo classic | Phase 3 `step_back_m` needs either a model-based human proxy, or regenerating the world or actor script per run. To be decided in Phase 3 |
| Robot pose source | AMCL (`/amcl_pose`) in localization mode; `nav2_goal_sender` uses TF `map→base_link` | Use `/amcl_pose` + `/tf` in bags. Ground-truth robot pose needs model states |
| Nav2 BT | Default `navigate_to_pose_w_replanning_and_recovery.xml`; behaviour server has spin/backup/wait | Recoveries can be counted from `/navigate_to_pose/_action/feedback` (`number_of_recoveries`) in Phase 5 |
| Incident log | Fixed path `~/compliance_robot_logs/incidents.jsonl`, shared across all runs. On startup it **deletes `*.jsonl` files older than `retention_days` (30)** | Batch runs should set a per-run `log_dir`. `incidents.jsonl` (1 record, last written 2026-07-30) is already older than 30 days, so **the next launch of either V2 or this copy will delete it**. The 336-record `incidents.jsonl.before-demo-20260730_1410` does not end in `.jsonl` and is safe |
| Persistence rate | cctv1 runs at 10 Hz (scenario publisher), cctv2 at up to 5 Hz (YOLO) | 5 frames ≈ 0.5 s on cctv1 and ≈ 1 s on cctv2. Report it as frames *and* seconds |
| SORT | Greedy IoU association (not Hungarian), constant-velocity Kalman with dt fixed at 0.1 s whatever the real frame rate. The tracker **overwrites the person bbox with the Kalman estimate** before confirmation | "SORT-inspired" is accurate. Bbox jitter in Phase 3 will be smoothed before C3 sees it |
| Model weights | `yoru_sim.yaml` uses `yolov8n.pt` (COCO) only; there is no specialist model in sim | All sim device detections are injected |
| `rosbags` | Not installed | Needed in Phase 5 |
| Old logs | `room_1`/`camera_*` entries use an older schema (`event_class: smoking`) | Exclude them from any analysis |

---

## 8. Open questions for you

1. **Sim time vs unchanged behaviour (§6).** The FSM, scenario publisher and goal sender all time
   themselves with the wall clock. Options:
   (a) leave them as they are, log RTF per run, and report durations in both clocks;
   (b) add a parameter `use_ros_clock` (default `false`, so behaviour is identical) that switches to
   `get_clock()`, and run the evaluation with it set to `true`.
   I recommend (b).
2. **Timing values for the paper (§4).** The brief's numbers (5 s / 3 s / 90 s / 3×8 s cap 30 / 10 s / 8 s)
   match neither the code defaults nor `yoru_sim.yaml`. Should the evaluation use `yoru_sim.yaml` as it is, or should
   I add an `evaluation/` parameter file with the brief's values, leaving the defaults untouched?
3. **The "uncertain lower bound = threshold − 0.20" rule (Phase 1).** It is currently an independent
   parameter (0.4). To keep the defaults identical I would keep `uncertain_confidence` and add the
   relative rule only for the batch runner (lower bound = τ − 0.20 when τ is overridden). Is that OK?
4. **Scenario B / C7.** Should Scenario B stay as it is (phone only, which tests C2 rather than C7), or should
   I add a variant with cigarette + phone at D < 0.75 so that C7 is actually exercised?
5. **The dissertation figure source.** If you can locate it, §3 can be confirmed.
6. **Human proxy for step-back and Scenario K (§7).** Is it acceptable to add a simple collidable
   cylinder model (moved with `set_entity_state`) alongside or instead of the actor for these scenarios?
   That would only change the evaluation worlds; the existing world stays as it is.

### Resolutions (2026-10-05)

The user asked for the most realistic simulation possible and delegated the remaining choices.

| Q | Decision |
|---|---|
| 1 | Implemented in Phase 1: `use_ros_clock` (default `false` = unchanged). Evaluation runs set it `true`. |
| 2 | The evaluation uses the brief's timings in a separate evaluation config; `yoru_sim.yaml` is unchanged. Reason: with the brief's 3 × 8 s warnings and a 10 s reset, "complies during S3" can produce `complied`, whereas `yoru_sim.yaml` forces S4 (§4 item 4). Every run records its full parameter set. |
| 3 | `uncertain_confidence` stays an independent parameter (default unchanged). The batch runner always sets it to τ − 0.20. |
| 4 | Scenario B is kept as it is (phone only, testing C2) **and** a C7 variant is added: cigarette + phone at the mouth with D below the 0.75 override, so C7 decides. |
| 5 | No figure source was found. §3 remains an inference from arithmetic, stated as such. |
| 6 | Evaluation worlds get a collidable, lidar-visible human proxy that can be moved with `set_entity_state` (step-back, Scenario K, ground-truth positions). The original `two_room_world.world` keeps its actors for demos. |
