# Recorded Simulation Walkthrough

A full end-to-end run of the system in simulation, screen-recorded with
audio (the PA announcement and the robot's warnings are audible).

**Video:** `recordings/yoru_full_demo_<date>.mp4` — 1920×1080, 4:00,
H.264 + AAC. Not committed to git (`recordings/` is ignored); re-record it
any time with the steps below.

**Screen layout:** Gazebo (left) shows the physical simulation — two rooms,
a doorway, the robot and two person actors. The admin dashboard (right) is
the real web console at `http://localhost:8080`.

## What happens, minute by minute

| Time | Phase | What to look for |
|---|---|---|
| 00:00 | Sign in, **Setup** screen | Setup checklist; "Mapping mode is ACTIVE". Top bar already shows **🚨 Smoking CONFIRMED · room_a** — the CCTV has detected the event, but the badge reads **Admin Control**, so the FSM is paused and will not dispatch yet |
| 00:01 | Admin control | Autonomy paused deliberately so mapping is not interrupted |
| 00:06 | **Map** screen — mapping drive begins | The robot drives itself around both rooms (lidar sweeps + waypoints). Watch the white/grey occupancy map grow from nothing into the two-room floor plan |
| 00:08 / 00:57 / 02:08 | Lidar sweeps | Rotation in place so the lidar sees the whole room |
| 02:41 | **Save Map** | Map written to `maps/sim/main_map.yaml`; checklist item 2 ticks off |
| 02:51 | Camera spot marked | `cctv1` spot saved at x=1.8, y=0.0 — the place the robot should drive to when this camera reports smoking. It appears as a purple marker on the map |
| 02:57 | **Resume autonomy** → robot on duty | Badge flips to **Autonomous**. View switches to **Cameras**: the live CCTV feed with YOLO detection boxes |
| 02:59 | **PA_WARNING** | Laptop speakers announce *"Attention. Smoking detected in room a. Smoking is not allowed here…"* (audible in the recording), then a grace period |
| 03:09 | **APPROACH** | Person keeps smoking → Nav2 dispatches the robot. View switches to **Map**: the blue robot arrow drives toward the red target dot |
| 03:17 | **DIRECT_WARNING** | Robot arrives and speaks the final warning **3 times**, 4 s apart (8 s apart on the real robot) |
| 03:29 | **LOGGING** | Escalation concludes |
| 03:31 | Incident logged + emailed | `room_a / cigarette / stage S4 / logged_no_compliance`; evidence email sent to the configured address **with 2 attachments** (CCTV frame + robot close-up) |
| 03:35 | **History** screen | The incident appears in the metadata-only violation log |

## Re-recording it

The choreography is scripted, so the run is repeatable:

```bash
# 1. fresh map so the demo starts from zero
rm -f maps/sim/main_map.*

# 2. start the simulation (no RViz, no auto-browser)
./start_sim.sh mode:=mapping rviz:=false open_browser:=false

# 3. IMMEDIATELY pause autonomy - the scenario's smoking event fires ~30 s
#    after start and the simulated person "complies" once warned, so the
#    event must be held pending until the recording is rolling
TOKEN=$(curl -s -X POST http://localhost:8080/api/login -d '{"password":"<pw>"}' \
        | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s -X POST -H "X-Auth: $TOKEN" http://localhost:8080/api/mode -d '{"paused":true}'

# 4. arrange windows: Gazebo left, a clean dashboard window right
wmctrl -r Gazebo -b remove,maximized_vert,maximized_horz
wmctrl -r Gazebo -e 0,0,0,1150,1080
google-chrome --user-data-dir=/tmp/yoru_demo --app="http://localhost:8080/#view=setup&pw=<pw>" \
              --window-size=770,1080 --window-position=1150,0

# 5. record screen + system audio
ffmpeg -y -f x11grab -framerate 25 -video_size 1920x1080 -i :0.0 \
       -f pulse -i "$(pactl get-default-sink).monitor" \
       -c:v libx264 -preset ultrafast -crf 24 -pix_fmt yuv420p \
       -c:a aac -b:a 128k recordings/demo.mp4

# 6. run the scripted walkthrough (--nav switches dashboard screens by
#    clicking the sidebar; the numbers are x,y_of_first_button,spacing)
python3 src/yoru_core/tools/sim_demo.py --password <pw> --nav 1273,185,54 \
        --timeline recordings/timeline.txt

# 7. stop the recording with Ctrl-C (or: pkill -INT -x ffmpeg)
```

## Notes

- **Simulation data is separate from the real robot.** The sim writes its
  map and camera spots to `maps/sim/`, so recording a demo can never
  overwrite the map and spots built on the real robot (`maps/`).
- The Gazebo world now opens on a fixed overview camera
  (`<gui><camera>` in `worlds/two_room_world.world`) so the rooms and the
  robot are framed correctly every launch.
- For a clean History screen, archive the incident log first:
  `mv ~/compliance_robot_logs/incidents.jsonl{,.bak}`.
- The scenario offends **once** per run: after the direct warning the
  simulated person complies and the device is removed. To demo the
  escalation again, restart the simulation.
