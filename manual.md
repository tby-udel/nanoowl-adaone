# ROS2-NanoOWL Manual

This is the day-to-day runbook for the working setup in `/home/ada2/boyang_ws`.

## 1. Start The Container

If the saved container already exists:

```bash
docker start isaac_ros_dev-aarch64-container
```

If you need to recreate it from the saved working image:

```bash
docker run -d \
  --name isaac_ros_dev-aarch64-container \
  --network host \
  --runtime nvidia \
  --privileged \
  --ipc host \
  --pid host \
  -e HOST_USER_UID=1000 \
  -e HOST_USER_GID=1000 \
  -e USERNAME=admin \
  -e ISAAC_ROS_WS=/workspaces/isaac_ros-dev \
  -v /home/ada2/boyang_ws:/workspaces/isaac_ros-dev \
  -v /etc/localtime:/etc/localtime:ro \
  -v /usr/bin/tegrastats:/usr/bin/tegrastats:ro \
  -v /usr/lib/aarch64-linux-gnu/tegra:/usr/lib/aarch64-linux-gnu/tegra:ro \
  -v /usr/src/jetson_multimedia_api:/usr/src/jetson_multimedia_api:ro \
  -v /usr/share/vpi3:/usr/share/vpi3:ro \
  --entrypoint /usr/local/bin/scripts/workspace-entrypoint.sh \
  isaac_ros_dev-aarch64:nanoowl-ready \
  /bin/bash -lc 'trap : TERM INT; sleep infinity & wait'
```

Optional shell:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash
```

## 2. Sample-Image Smoke Test

Use this before the camera if you want a quick install check.

Terminal 1:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
ros2 run image_publisher image_publisher_node /workspaces/isaac_ros-dev/src/nanoowl/assets/owl_glove_small.jpg --ros-args --remap /image_raw:=/input_image
'
```

Terminal 2:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
ros2 launch ros2_nanoowl nano_owl_example.launch.py thresholds:=0.1 image_encoder_engine:=/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owl_image_encoder_patch32.engine
'
```

Terminal 3:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
ros2 topic pub -1 /input_query std_msgs/msg/String "data: an owl, a glove"
'
```

Terminal 4:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
ros2 topic echo /output_detections --once
'
```

## 3. Live Camera Startup

Start the RealSense node on the host first. Keep these environment variables the same on both host and container.

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run realsense2_camera realsense2_camera_node --ros-args -p enable_depth:=false -p enable_infra1:=false -p enable_infra2:=false -p enable_gyro:=false -p enable_accel:=false
```

Success sign:

- The terminal prints `RealSense Node Is Up!`

## 4. Fast GPU Detection Mode

Use this when you want the highest throughput and do not need the annotated image topic.

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 run ros2_nanoowl nano_owl_py --ros-args \
  -r input_image:=/camera/camera/color/image_raw \
  -p device:=cuda \
  -p image_encoder_engine:=/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owl_image_encoder_patch32.engine \
  -p thresholds:=0.05 \
  -p publish_output_image:=false
'
```

Observed result on this machine:

- about `10 Hz` on `/output_detections`

Important:

- `publish_output_image:=false` means `/output_image` will not publish frames for RViz.
- This is the preferred mode when you only care about detections.

## 5. Visualization GPU Mode

Use this when you want to see the annotated camera image in RViz.

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 run ros2_nanoowl nano_owl_py --ros-args \
  -r input_image:=/camera/camera/color/image_raw \
  -p device:=cuda \
  -p image_encoder_engine:=/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owl_image_encoder_patch32.engine \
  -p thresholds:=0.05 \
  -p publish_output_image:=true
'
```

Observed result on this machine:

- about `7 Hz` on `/output_image`
- about `8.4 Hz` on `/output_detections`

Important:

- Use either fast mode or visualization mode, not both at once.
- The correct RViz topic is `/output_image`.

## 6. Publish The Query

From the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic pub -1 /input_query std_msgs/msg/String "data: a person, a monitor, a chair"
```

## 7. Check Detections

Container-side watch:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 topic echo /output_detections
'
```

One-shot check:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 topic echo /output_detections --once
'
```

Rate check:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 topic hz /output_detections
'
```

Host-side note:

- `ros2 topic echo /output_detections` on the host needs `vision_msgs` installed in the host ROS environment.
- If that package is missing, use the container commands above.

## 8. Visualize In RViz

Start RViz from the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
rviz2
```

Inside RViz:

- Add an `Image` display.
- Set Topic to `/output_image`.
- If the view stays blank, set Reliability Policy to `Reliable`.

Quick one-shot topic check from the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /output_image --once
```

## 9. Useful Checks

Confirm camera topics on the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic list | grep '^/camera/'
```

Confirm container nodes:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 node list
'
```

Confirm NanoOWL is publishing:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 topic info /output_detections -v
'
```

## 10. Query Index Mapping

`class_id` in `/output_detections` is the index of the phrase in your query.

Example query:

```text
a person, a monitor, a chair
```

Mapping:

- `0` = `a person`
- `1` = `a monitor`
- `2` = `a chair`

## 11. Shutdown

Stop the host camera:

```bash
pkill -f realsense2_camera_node || true
```

Stop NanoOWL in the container:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc "pkill -f nano_owl_py || true"
```

Stop the container:

```bash
docker stop isaac_ros_dev-aarch64-container
```
