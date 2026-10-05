"""Launch all Yoru compliance nodes.

Per-CCTV pipeline instances (yolo -> tracking -> confirmation -> camera
target) plus the shared decision/intervention nodes. Node names match the
parameter file keys (yolo_cctv1, tracking_cctv1, confirm_cctv1,
camera_target_cctv1, ...).

V2: the coordinate transform is replaced by camera_target_node - each
camera's confirmed events resolve to the camera spot the admin marked on
the map in the dashboard (maps/cameras.json).

Arguments:
  params_file     : node parameter YAML (default: yoru_sim.yaml)
  use_sim_time    : true in Gazebo, false on hardware
  use_scenario    : start the scenario publisher (simulation testing only)
  use_cctv2       : start the second camera pipeline (two-room sim)
  use_audio_node  : start an audio node here
  audio_node_name : which config section drives the audio node -
                    'audio_warning_node' (speaks everything - sim),
                    'pa_audio_node' (server: PA announcement only; the
                    robot's own speaker delivers the direct warning)

Evaluation overrides (empty = keep the params_file value):
  w_D, w_P, w_T, w_S   : confirmation weights (device, proximity,
                         persistence, support) for every confirm_cctvN node
  confirm_confidence   : confirmation threshold
  uncertain_confidence : lower bound of the 'uncertain' band
  use_ros_clock        : true = FSM, scenario publisher and goal sender time
                         themselves on the node clock (sim time) instead of
                         the wall clock
  use_actors           : start human_actor_node (evaluation world only)
  overlay_params       : extra parameter YAML applied to every node after
                         params_file (evaluation runs: per-run settings)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


CONFIRM_OVERRIDES = ('w_D', 'w_P', 'w_T', 'w_S',
                     'confirm_confidence', 'uncertain_confidence')
CLOCK_OVERRIDES = ('use_ros_clock',)
OVERRIDE_ARGS = CONFIRM_OVERRIDES + CLOCK_OVERRIDES + ('overlay_params',)


def overrides(context, names, cast):
    """Only the override arguments actually given, so the params_file
    stays authoritative for everything left empty."""
    values = {}
    for name in names:
        value = LaunchConfiguration(name).perform(context).strip()
        if value:
            values[name] = cast(value)
    return values


def launch_nodes(context):
    params_file = LaunchConfiguration('params_file')
    use_sim_time = LaunchConfiguration('use_sim_time')
    use_scenario = LaunchConfiguration('use_scenario')
    use_cctv2 = LaunchConfiguration('use_cctv2')
    use_audio_node = LaunchConfiguration('use_audio_node')
    overlay = LaunchConfiguration('overlay_params').perform(context).strip()
    confirm = overrides(context, CONFIRM_OVERRIDES, float)
    clock = overrides(context, CLOCK_OVERRIDES, lambda v: v.lower() == 'true')
    use_actors = LaunchConfiguration('use_actors').perform(context).strip().lower() == 'true'

    def yoru_node(executable, name=None, extra_params=None, **kwargs):
        # No evaluation arguments -> exactly [params_file, use_sim_time]
        parameters = [params_file, {'use_sim_time': use_sim_time}]
        if overlay:
            parameters.append(overlay)
        if extra_params:
            parameters.append(extra_params)
        return Node(
            package='yoru_core',
            executable=executable,
            name=name,
            output='screen',
            parameters=parameters,
            **kwargs)

    cctv2_cond = IfCondition(use_cctv2)

    return [
        # --- CCTV 1 pipeline ---
        yoru_node('yolo_detector_node', name='yolo_cctv1'),
        yoru_node('scenario_publisher_node', extra_params=clock,
                  condition=IfCondition(use_scenario)),
        yoru_node('tracking_node', name='tracking_cctv1'),
        yoru_node('event_confirmation_node', name='confirm_cctv1',
                  extra_params=confirm),
        yoru_node('camera_target_node', name='camera_target_cctv1'),

        # --- CCTV 2 pipeline (two-room sim world) ---
        yoru_node('yolo_detector_node', name='yolo_cctv2',
                  condition=cctv2_cond),
        yoru_node('tracking_node', name='tracking_cctv2',
                  condition=cctv2_cond),
        yoru_node('event_confirmation_node', name='confirm_cctv2',
                  extra_params=confirm, condition=cctv2_cond),
        yoru_node('camera_target_node', name='camera_target_cctv2',
                  condition=cctv2_cond),

        # --- Shared decision / intervention nodes ---
        yoru_node('nav2_goal_sender_node', extra_params=clock),
        yoru_node('compliance_fsm_node', extra_params=clock),
        yoru_node('audio_warning_node',
                  name=LaunchConfiguration('audio_node_name'),
                  condition=IfCondition(use_audio_node)),
        yoru_node('incident_logger_node'),
        yoru_node('incident_emailer_node'),
        yoru_node('patrol_node'),
        yoru_node('return_to_base_node'),
        yoru_node('admin_joy_node'),
        yoru_node('dashboard_node'),
    ] + ([
        # --- Simulated human response model (eval_two_room.world) ---
        yoru_node('human_actor_node'),
    ] if use_actors else [])


def generate_launch_description():
    bringup_dir = get_package_share_directory('yoru_bringup')
    default_params = os.path.join(bringup_dir, 'config', 'yoru_sim.yaml')

    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=default_params),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('use_scenario', default_value='false'),
        DeclareLaunchArgument('use_cctv2', default_value='true'),
        DeclareLaunchArgument('use_audio_node', default_value='true'),
        DeclareLaunchArgument('audio_node_name',
                              default_value='audio_warning_node'),
        DeclareLaunchArgument('use_actors', default_value=''),
        *[DeclareLaunchArgument(name, default_value='')
          for name in OVERRIDE_ARGS],
        OpaqueFunction(function=launch_nodes),
    ])
