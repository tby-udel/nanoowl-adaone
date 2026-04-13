#!/bin/bash

cd /f1tenth_ws
source install_foxy/setup.bash
exec ros2 launch f1tenth_stack bringup_launch.py vesc_config:=/f1tenth_ws/vesc_usb0_test.yaml
