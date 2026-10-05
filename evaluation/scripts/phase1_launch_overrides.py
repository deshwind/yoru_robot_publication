#!/usr/bin/env python3
"""Phase 1 evidence: which parameters each decision node receives from launch.

Evaluates full_system.launch.py's override OpaqueFunction with no arguments
(must add nothing beyond params_file + use_sim_time) and with overrides.

Usage (workspace built and sourced):
  python3 evaluation/scripts/phase1_launch_overrides.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.utilities import normalize_to_list_of_substitutions, perform_substitutions

LAUNCH = os.path.join(get_package_share_directory('yoru_bringup'),
                      'launch', 'full_system.launch.py')


def text(ctx, value):
    if value is None or isinstance(value, str):
        return value
    return perform_substitutions(ctx, normalize_to_list_of_substitutions(value))


def resolve(args):
    description = PythonLaunchDescriptionSource(LAUNCH).get_launch_description(
        LaunchContext())
    ctx = LaunchContext()
    for entity in description.entities:
        if isinstance(entity, DeclareLaunchArgument):
            ctx.launch_configurations[entity.name] = args.get(
                entity.name, perform_substitutions(ctx, entity.default_value))
    nodes = {}
    for entity in description.entities:
        if isinstance(entity, OpaqueFunction):
            for node in entity.execute(ctx):
                name = text(ctx, node._Node__node_name) or node._Node__node_executable
                params = node._Node__parameters
                extra = {}
                for p in params[2:]:
                    if isinstance(p, dict):
                        extra.update({text(ctx, k): v for k, v in p.items()})
                    else:
                        extra['<file>'] = text(ctx, p)
                nodes[name] = (len(params), extra)
    return nodes


def main():
    cases = {
        'no arguments': {},
        'w_D=0.5 w_S=0.1 confirm_confidence=0.7 use_ros_clock=true': {
            'w_D': '0.5', 'w_S': '0.1', 'confirm_confidence': '0.7',
            'use_ros_clock': 'true'},
    }
    for label, args in cases.items():
        print(f'--- {label}')
        for name, (count, extra) in resolve(args).items():
            print(f'  {name:26s} parameter entries={count}  extra={extra}')


if __name__ == '__main__':
    main()
