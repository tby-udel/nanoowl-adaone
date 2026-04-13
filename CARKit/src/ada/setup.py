from setuptools import setup, find_packages
from glob import glob
import os

package_name = 'ada'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('lib', package_name), [
            'ada/interactive_waypoints.py',
            'ada/demo1.py',
            'ada/demo2.py',
            'ada/distance_metrics.py',
            'ada/object_angle.py',
            'ada/object_position.py',
            'ada/path_tracker.py',
            'ada/cmd_vel_to_ackermann.py',
            'ada/scene_aware_query_manager.py',
            'ada/reactive_behavior_controller.py',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ada',
    maintainer_email='ada@todo.todo',
    description='Ada autonomous driving system integration package',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'interactive_waypoints = ada.interactive_waypoints:main',
            'demo1 = ada.demo1:main',
            'demo2 = ada.demo2:main',
            'distance_metrics = ada.distance_metrics:main',
            'object_angle = ada.object_angle:main',
            'object_position = ada.object_position:main',
            'path_tracker = ada.path_tracker:main',
            'cmd_vel_to_ackermann = ada.cmd_vel_to_ackermann:main',
            'scene_aware_query_manager = ada.scene_aware_query_manager:main',
            'reactive_behavior_controller = ada.reactive_behavior_controller:main',
        ],
    },
) 
