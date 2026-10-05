"""ONE-COMMAND simulation: robot + server together (Yoru V2).

    ./start_sim.sh          (which runs: ros2 launch yoru_bringup sim_full.launch.py)

Combines the two halves in a single process:
  - sim.launch.py    : Gazebo two-room world + robot + SLAM/AMCL + Nav2 + RViz
  - server.launch.py : CCTV perception + PA voice + FSM + dashboard (sim:=true)

This is exactly equivalent to running ./start_sim.sh robot and
./start_server.sh sim in two terminals - use those when you want the
server logs separated (e.g. mirroring the real laptop + Pi deployment).

Arguments (all forwarded):
  mode         : auto (default) | mapping | localization
  map          : saved map yaml (default: ~/Yoru_bot_publication/maps/main_map.yaml)
  gui / rviz   : Gazebo GUI / RViz (default: true)
  open_browser : auto-open the dashboard (default: true)
  use_joystick : PS4 admin joystick (default: true)
  w_D, w_P, w_T, w_S, confirm_confidence, uncertain_confidence,
  use_ros_clock, overlay_params : evaluation overrides (empty = keep
                  yoru_sim.yaml values)
  world        : Gazebo world (default: two_room_world.world)
  spawn_x/y/yaw: robot start pose, also AMCL's initial pose (default 0 0 0)
  bag_path     : record a rosbag2 of the evaluation topics to this directory
                 (empty = no recording)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess,
                            IncludeLaunchDescription, OpaqueFunction)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

EVAL_OVERRIDE_ARGS = ('w_D', 'w_P', 'w_T', 'w_S', 'confirm_confidence',
                      'uncertain_confidence', 'use_ros_clock',
                      'overlay_params', 'use_actors')
DEFAULT_MAP = os.path.expanduser('~/Yoru_bot_publication/maps/sim/main_map.yaml')

# Everything the evaluation metrics are computed from (evaluation/README.md)
BAG_TOPICS = [
    '/clock',
    # decision pipeline + instrumentation
    '/compliance/fsm_state', '/compliance/fsm_status',
    '/compliance/confirmation_debug', '/compliance/event_metadata',
    '/compliance/cctv1/confirmed', '/compliance/cctv2/confirmed',
    '/compliance/tracking_info',
    '/compliance/audio_event', '/compliance/pa_warning',
    '/compliance/direct_warning',
    '/compliance/scenario_ground_truth',
    '/compliance/incident_log', '/compliance/incident_log_path',
    '/compliance/autonomy_paused',
    # navigation
    '/compliance/navigation_targets', '/compliance/nav_status',
    '/navigate_to_pose/_action/status', '/navigate_to_pose/_action/feedback',
    '/plan', '/amcl_pose', '/odom', '/diff_cont/odom',
    '/cmd_vel_tracker', '/diff_cont/cmd_vel_unstamped',
    # ground truth + safety
    '/gazebo/model_states', '/scan', '/tf', '/tf_static',
    # simulated human response model
    '/compliance/actor_events', '/person_1/cmd_pose', '/person_2/cmd_pose',
    '/person_3/cmd_pose', '/intruder_1/cmd_pose',
]


def bag_recorder(context):
    path = LaunchConfiguration('bag_path').perform(context).strip()
    if not path:
        return []
    return [ExecuteProcess(
        cmd=['ros2', 'bag', 'record', '-o', os.path.expanduser(path),
             '--include-hidden-topics'] + BAG_TOPICS,
        output='screen')]


def generate_launch_description():
    launch_dir = os.path.join(
        get_package_share_directory('yoru_bringup'), 'launch')

    declare_args = [
        DeclareLaunchArgument('mode', default_value='auto',
                              description='auto | mapping | localization'),
        DeclareLaunchArgument('map', default_value=DEFAULT_MAP),
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('open_browser', default_value='true'),
        DeclareLaunchArgument('use_joystick', default_value='true'),
        DeclareLaunchArgument(
            'world', default_value=os.path.join(
                get_package_share_directory('yoru_bringup'), 'worlds',
                'two_room_world.world')),
        DeclareLaunchArgument('bag_path', default_value=''),
        DeclareLaunchArgument('spawn_x', default_value='0.0'),
        DeclareLaunchArgument('spawn_y', default_value='0.0'),
        DeclareLaunchArgument('spawn_yaw', default_value='0.0'),
        *[DeclareLaunchArgument(name, default_value='')
          for name in EVAL_OVERRIDE_ARGS],
    ]

    sim_args = {
        'mode': LaunchConfiguration('mode'),
        'map': LaunchConfiguration('map'),
        'gui': LaunchConfiguration('gui'),
        'rviz': LaunchConfiguration('rviz'),
        'world': LaunchConfiguration('world'),
        'spawn_x': LaunchConfiguration('spawn_x'),
        'spawn_y': LaunchConfiguration('spawn_y'),
        'spawn_yaw': LaunchConfiguration('spawn_yaw'),
    }
    robot_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_dir, 'sim.launch.py')),
        launch_arguments=sim_args.items())

    server = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_dir, 'server.launch.py')),
        launch_arguments={
            'sim': 'true',
            'open_browser': LaunchConfiguration('open_browser'),
            'use_joystick': LaunchConfiguration('use_joystick'),
            **{name: LaunchConfiguration(name)
               for name in EVAL_OVERRIDE_ARGS},
        }.items())

    return LaunchDescription(declare_args + [
        OpaqueFunction(function=bag_recorder), robot_sim, server])
