"""SERVER side - run this on the laptop (Yoru V2).

    ros2 launch yoru_bringup server.launch.py            # real robot
    ros2 launch yoru_bringup server.launch.py sim:=true  # with the simulation

The laptop is both the CCTV camera and the brain:
  - CCTV perception (YOLO -> tracking -> confirmation -> camera-spot target).
    Real: the laptop webcam is the CCTV. Sim: the Gazebo CCTV image topics.
  - PA announcement through the laptop speakers ("Smoking is not allowed...")
  - escalation FSM, Nav2 goal sender, return-to-base
  - admin dashboard (auto-opens in the browser: first-run password setup,
    mapping drive, camera spots, live views, history)
  - incident logger + Gmail evidence emailer
  - admin joystick (PS4 controller paired with this laptop)

The robot half runs real_robot.launch.py on the Raspberry Pi (or
sim.launch.py in another terminal for testing). Both machines just need the
same ROS_DOMAIN_ID (source ros_network.env on both); topics, actions and TF
flow over Wi-Fi automatically.

Arguments:
  sim          : true = simulation profile (yoru_sim.yaml, sim time,
                 scenario publisher, both CCTV pipelines, single audio node)
  use_cctv2    : second CCTV pipeline (default: sim value)
  use_joystick : PS4 admin joystick on this laptop (default true)
  open_browser : open the dashboard automatically (default true)
  w_D, w_P, w_T, w_S, confirm_confidence, uncertain_confidence,
  use_ros_clock : evaluation overrides forwarded to full_system.launch.py
                  (empty = keep the YAML value)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess,
                            IncludeLaunchDescription, OpaqueFunction,
                            TimerAction)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

EVAL_OVERRIDE_ARGS = ('w_D', 'w_P', 'w_T', 'w_S', 'confirm_confidence',
                      'uncertain_confidence', 'use_ros_clock',
                      'overlay_params', 'use_actors')


def launch_compliance(context):
    """Resolves the sim/real profile into full_system.launch.py arguments."""
    bringup_dir = get_package_share_directory('yoru_bringup')
    sim = LaunchConfiguration('sim').perform(context).lower() == 'true'
    use_cctv2 = LaunchConfiguration('use_cctv2').perform(context)
    if use_cctv2 == 'auto':
        # Two CCTV pipelines everywhere: sim has two room cameras, real has
        # the built-in webcam (cctv1) + the Logitech C920 (cctv2). Pass
        # use_cctv2:=false if the second camera is unplugged.
        use_cctv2 = 'true'

    config = 'yoru_sim.yaml' if sim else 'yoru_real.yaml'
    print(f'[yoru] server profile: {"SIMULATION" if sim else "REAL ROBOT"} '
          f'({config})')

    return [IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'full_system.launch.py')),
        launch_arguments={
            'params_file': os.path.join(bringup_dir, 'config', config),
            'use_sim_time': str(sim).lower(),
            'use_scenario': str(sim).lower(),
            'use_cctv2': use_cctv2,
            # Sim: one audio node speaks PA + direct warning on this machine.
            # Real: the laptop speaks the PA only; the robot's own speaker
            # (real_robot.launch.py) delivers the close-range direct warning.
            'audio_node_name': ('audio_warning_node' if sim
                                else 'pa_audio_node'),
            **{name: LaunchConfiguration(name)
               for name in EVAL_OVERRIDE_ARGS},
        }.items())]


def generate_launch_description():
    yoru_base_dir = get_package_share_directory('yoru_base')

    declare_args = [
        DeclareLaunchArgument('sim', default_value='false'),
        DeclareLaunchArgument('use_cctv2', default_value='auto'),
        DeclareLaunchArgument('open_browser', default_value='true'),
        DeclareLaunchArgument('use_joystick', default_value='true'),
        *[DeclareLaunchArgument(name, default_value='')
          for name in EVAL_OVERRIDE_ARGS],
    ]

    compliance = OpaqueFunction(function=launch_compliance)

    # Admin joystick paired with this PC; /cmd_vel_joy crosses the network
    # to the robot's twist_mux at the highest priority.
    joystick = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(yoru_base_dir, 'launch', 'joystick.launch.py')),
        launch_arguments={'use_sim_time': LaunchConfiguration('sim')}.items(),
        condition=IfCondition(LaunchConfiguration('use_joystick')))

    open_dashboard = ExecuteProcess(
        cmd=['bash', '-c',
             'for i in $(seq 1 30); do '
             'curl -s -o /dev/null http://localhost:8080/ && break; sleep 1; '
             'done; xdg-open http://localhost:8080 || true'],
        condition=IfCondition(LaunchConfiguration('open_browser')),
        output='screen')

    return LaunchDescription(declare_args + [
        compliance,
        joystick,
        TimerAction(period=3.0, actions=[open_dashboard]),
    ])
