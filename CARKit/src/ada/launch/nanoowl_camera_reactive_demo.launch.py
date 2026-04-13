from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    launch_args = [
        DeclareLaunchArgument('scene_override', default_value='auto'),
        DeclareLaunchArgument(
            'scene_neutral_labels',
            default_value='person, people, pedestrian, pedestrians, human, humans',
        ),
        DeclareLaunchArgument(
            'indoor_probe_query',
            default_value='person, people, chair, desk, monitor, bottle, laptop',
        ),
        DeclareLaunchArgument(
            'outdoor_probe_query',
            default_value='pedestrian, bicyclist, bicycle, motorcycle, car, truck, bus, stop sign, traffic light, cone',
        ),
        DeclareLaunchArgument(
            'indoor_query',
            default_value='person, people, chair, desk, monitor, bottle, laptop, keyboard, cup, box',
        ),
        DeclareLaunchArgument(
            'outdoor_query',
            default_value='pedestrian, bicyclist, bicycle, motorcycle, car, truck, bus, stop sign, traffic light, cone, box',
        ),
        DeclareLaunchArgument('motion_enabled', default_value='false'),
        DeclareLaunchArgument('cruise_speed', default_value='0.35'),
        DeclareLaunchArgument('slow_speed', default_value='0.18'),
        DeclareLaunchArgument('bypass_speed', default_value='0.12'),
        DeclareLaunchArgument('stop_labels', default_value='person, stop sign'),
        DeclareLaunchArgument('slow_labels', default_value='cone, chair, box'),
        DeclareLaunchArgument('bypass_labels', default_value='cone, chair, box'),
    ]

    scene_manager = Node(
        package='ada',
        executable='scene_aware_query_manager',
        name='scene_aware_query_manager',
        output='screen',
        parameters=[{
            'scene_override': LaunchConfiguration('scene_override'),
            'scene_neutral_labels': LaunchConfiguration('scene_neutral_labels'),
            'indoor_probe_query': LaunchConfiguration('indoor_probe_query'),
            'outdoor_probe_query': LaunchConfiguration('outdoor_probe_query'),
            'indoor_query': LaunchConfiguration('indoor_query'),
            'outdoor_query': LaunchConfiguration('outdoor_query'),
        }],
    )

    reactive_controller = Node(
        package='ada',
        executable='reactive_behavior_controller',
        name='reactive_behavior_controller',
        output='screen',
        parameters=[{
            'motion_enabled': LaunchConfiguration('motion_enabled'),
            'cruise_speed': LaunchConfiguration('cruise_speed'),
            'slow_speed': LaunchConfiguration('slow_speed'),
            'bypass_speed': LaunchConfiguration('bypass_speed'),
            'stop_labels': LaunchConfiguration('stop_labels'),
            'slow_labels': LaunchConfiguration('slow_labels'),
            'bypass_labels': LaunchConfiguration('bypass_labels'),
        }],
    )

    return LaunchDescription(launch_args + [scene_manager, reactive_controller])
