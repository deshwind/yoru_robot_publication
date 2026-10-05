import os
from glob import glob

from setuptools import setup

package_name = 'yoru_core'

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'audio'),
            glob('audio/*.wav') + glob('audio/*.mp3')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Deshwin Dharile',
    maintainer_email='deshwind02@gmail.com',
    description='Yoru V2 - CCTV-triggered compliance robot core nodes',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'yolo_detector_node = yoru_core.yolo_detector_node:main',
            'scenario_publisher_node = yoru_core.scenario_publisher_node:main',
            'tracking_node = yoru_core.tracking_node:main',
            'event_confirmation_node = yoru_core.event_confirmation_node:main',
            'camera_target_node = yoru_core.camera_target_node:main',
            'nav2_goal_sender_node = yoru_core.nav2_goal_sender_node:main',
            'compliance_fsm_node = yoru_core.compliance_fsm_node:main',
            'audio_warning_node = yoru_core.audio_warning_node:main',
            'incident_logger_node = yoru_core.incident_logger_node:main',
            'incident_emailer_node = yoru_core.incident_emailer_node:main',
            'patrol_node = yoru_core.patrol_node:main',
            'return_to_base_node = yoru_core.return_to_base_node:main',
            'l298n_driver_node = yoru_core.l298n_driver_node:main',
            'arduino_driver_node = yoru_core.arduino_driver_node:main',
            'map_reset_node = yoru_core.map_reset_node:main',
            'admin_joy_node = yoru_core.admin_joy_node:main',
            'dashboard_node = yoru_core.dashboard_node:main',
            'camera_publisher_node = yoru_core.camera_publisher_node:main',
            'human_actor_node = yoru_core.human_actor_node:main',
        ],
    },
)
