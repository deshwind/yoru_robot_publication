"""SIMULATED ROBOT bring-up (Yoru V2) - the sim stand-in for the real robot.

    Terminal 1:  ./start_sim.sh          (this launch)
    Terminal 2:  ./start_server.sh sim   (perception + FSM + dashboard)

Mirrors the real deployment split: this launch is everything that would run
on the robot itself - robot description + Gazebo (two-room world with CCTV
cameras) + ros2_control + twist_mux + SLAM or AMCL + Nav2 + RViz. The
server terminal runs the CCTV perception, escalation FSM and the admin
dashboard, exactly like it does for the real robot.

First run (no saved map): boots in MAPPING mode - drive with the keyboard
from the dashboard Setup screen (or the joystick), press Save Map, mark the
camera spots, then relaunch. With a saved map it boots in LOCALIZATION mode
and goes straight on duty.

Arguments:
  mode        : auto (default) | mapping | localization
                auto = mapping if maps/main_map.yaml is missing, else localization
  map         : saved map yaml (default: ~/Yoru_bot_publication/maps/main_map.yaml)
  world       : Gazebo world file (default: two_room_world.world)
  rviz        : start RViz (default: true)
  gui         : start the Gazebo GUI client (default: true)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, IncludeLaunchDescription,
                            OpaqueFunction, TimerAction)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

DEFAULT_MAP = os.path.expanduser('~/Yoru_bot_publication/maps/sim/main_map.yaml')


def resolve_mode(context):
    """mode:=auto -> mapping when no saved map exists, else localization."""
    mode = LaunchConfiguration('mode').perform(context)
    map_file = LaunchConfiguration('map').perform(context)
    if mode == 'auto':
        mode = 'localization' if os.path.isfile(map_file) else 'mapping'
        print(f'[yoru] mode:=auto resolved to "{mode}" '
              f'(map {"found" if mode == "localization" else "not found"}: '
              f'{map_file})')

    yoru_base_dir = get_package_share_directory('yoru_base')
    actions = []
    if mode == 'mapping':
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(yoru_base_dir, 'launch', 'online_async_launch.py')),
            launch_arguments={
                'use_sim_time': 'true',
                'params_file': os.path.join(yoru_base_dir, 'config',
                                            'mapper_params_online_async.yaml'),
            }.items()))
    else:
        actions.append(IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(yoru_base_dir, 'launch', 'localization_launch.py')),
            launch_arguments={
                'map': map_file,
                'use_sim_time': 'true',
                'params_file': os.path.join(yoru_base_dir, 'config',
                                            'nav2_params.yaml'),
                # AMCL starts where the robot was spawned
                'initial_x': LaunchConfiguration('spawn_x'),
                'initial_y': LaunchConfiguration('spawn_y'),
                'initial_yaw': LaunchConfiguration('spawn_yaw'),
            }.items()))
    return [TimerAction(period=5.0, actions=actions)]


def generate_launch_description():
    bringup_dir = get_package_share_directory('yoru_bringup')
    yoru_base_dir = get_package_share_directory('yoru_base')

    world = LaunchConfiguration('world')
    gui = LaunchConfiguration('gui')
    rviz = LaunchConfiguration('rviz')

    declare_args = [
        DeclareLaunchArgument('mode', default_value='auto',
                              description='auto | mapping | localization'),
        DeclareLaunchArgument('map', default_value=DEFAULT_MAP),
        DeclareLaunchArgument(
            'world',
            default_value=os.path.join(bringup_dir, 'worlds',
                                       'two_room_world.world')),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('gui', default_value='true'),
        # Robot start / base pose (evaluation: room B); 0 = doorway, as before
        DeclareLaunchArgument('spawn_x', default_value='0.0'),
        DeclareLaunchArgument('spawn_y', default_value='0.0'),
        DeclareLaunchArgument('spawn_yaw', default_value='0.0'),
    ]

    # --- Robot description (URDF via xacro, with ros2_control for sim) ---
    rsp = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(yoru_base_dir, 'launch', 'rsp.launch.py')),
        launch_arguments={'use_sim_time': 'true',
                          'use_ros2_control': 'true'}.items())

    # --- Gazebo with the compliance world ---
    gazebo_params = os.path.join(yoru_base_dir, 'config', 'gazebo_params.yaml')
    gazebo = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('gazebo_ros'),
                         'launch', 'gazebo.launch.py')),
        launch_arguments={
            'world': world,
            'gui': gui,
            'extra_gazebo_args': '--ros-args --params-file ' + gazebo_params,
        }.items())

    spawn_entity = Node(
        package='gazebo_ros', executable='spawn_entity.py',
        arguments=['-topic', 'robot_description', '-entity', 'yoru_robot',
                   '-x', LaunchConfiguration('spawn_x'),
                   '-y', LaunchConfiguration('spawn_y'), '-z', '0.05',
                   '-Y', LaunchConfiguration('spawn_yaw')],
        output='screen')

    diff_drive_spawner = Node(package='controller_manager', executable='spawner',
                              arguments=['diff_cont'])
    joint_broad_spawner = Node(package='controller_manager', executable='spawner',
                               arguments=['joint_broad'])

    twist_mux_params = os.path.join(yoru_base_dir, 'config', 'twist_mux.yaml')
    twist_mux = Node(
        package='twist_mux', executable='twist_mux',
        parameters=[twist_mux_params, {'use_sim_time': True}],
        remappings=[('/cmd_vel_out', '/diff_cont/cmd_vel_unstamped')])

    # --- SLAM (mapping) or AMCL (saved map): resolved by mode:=auto ---
    slam_or_amcl = OpaqueFunction(function=resolve_mode)

    # --- Nav2 ---
    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(yoru_base_dir, 'launch', 'navigation_launch.py')),
        launch_arguments={
            'use_sim_time': 'true',
            'params_file': os.path.join(yoru_base_dir, 'config',
                                        'nav2_params.yaml'),
        }.items())

    # Static TFs for the CCTV cameras (visualisation; match the world poses)
    cctv1_tf = Node(
        package='tf2_ros', executable='static_transform_publisher',
        name='cctv1_tf',
        arguments=['--x', '5.8', '--y', '0', '--z', '2.5',
                   '--roll', '0', '--pitch', '0.55', '--yaw', '3.14159',
                   '--frame-id', 'map', '--child-frame-id', 'cctv1_link'],
        output='screen')
    cctv2_tf = Node(
        package='tf2_ros', executable='static_transform_publisher',
        name='cctv2_tf',
        arguments=['--x', '-5.8', '--y', '0', '--z', '2.5',
                   '--roll', '0', '--pitch', '0.55', '--yaw', '0',
                   '--frame-id', 'map', '--child-frame-id', 'cctv2_link'],
        output='screen')

    rviz_node = Node(
        package='rviz2', executable='rviz2',
        arguments=['-d', os.path.join(bringup_dir, 'rviz', 'compliance.rviz')],
        parameters=[{'use_sim_time': True}],
        condition=IfCondition(rviz),
        output='screen')

    return LaunchDescription(declare_args + [
        rsp,
        twist_mux,
        gazebo,
        spawn_entity,
        diff_drive_spawner,
        joint_broad_spawner,
        cctv1_tf,
        cctv2_tf,
        slam_or_amcl,
        TimerAction(period=8.0, actions=[nav2]),
        TimerAction(period=6.0, actions=[rviz_node]),
    ])
