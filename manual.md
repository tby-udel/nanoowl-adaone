# ADAONE + NanoOWL Manual

This is the short operational runbook for the current project state.

Use [instructions.md](/home/ada2/boyang_ws/instructions.md) for full install/build details.
Use [ADAONE_SYSTEM_CHANGES.md](/home/ada2/boyang_ws/ADAONE_SYSTEM_CHANGES.md) for the cross-system change history.

## Current Defaults

Current recommended NanoOWL deployment target:

- model:
  - `/workspaces/isaac_ros-dev/models/owlvit_deal_imagenet_step55_hf`
- engine:
  - `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`

Important note:

- the older `/workspaces/isaac_ros-dev/my_model` workflow is historical and should not be treated as the default path anymore

## 1. Proper Low-Level Wheel Driver Path

If you need the wheel driver or chassis stack, use the explicit `ada_system` Docker workflow.

Host terminal:

```bash
cd /home/ada2/ada_system
./run_container.sh
```

Inside that container:

```bash
source install_foxy/setup.bash
ros2 launch f1tenth_stack bringup_launch.py
```

Important:

- `install_foxy/setup.bash` is the correct environment for this machine
- `install/setup.bash` was stale for the low-level chassis stack
- the successful wheel-motion test used the VESC serial device `/dev/ttyACM0`

## 2. Start The Host ADAONE Stack

Host terminal:

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/CARKit/install/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 launch ada ada_system.launch.py
```

This is the current convenient host-side bring-up for:

- camera
- LiDAR
- LiDAR transformer
- LiDAR localization
- control center

## 3. Start The Isaac ROS NanoOWL Container

```bash
docker start isaac_ros_dev-aarch64-container
```

Optional shell:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash
```

## 4. Recommended NanoOWL Runtime

Container terminal:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
export PYTHONPATH=/workspaces/isaac_ros-dev/src/nanoowl:$PYTHONPATH
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run ros2_nanoowl nano_owl_py --ros-args \
  -r input_image:=/camera/camera/color/image_raw \
  -p model:=/workspaces/isaac_ros-dev/models/owlvit_deal_imagenet_step55_hf \
  -p device:=cuda \
  -p image_encoder_engine:=/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine \
  -p thresholds:=0.05 \
  -p publish_output_image:=false \
  -p publish_legacy_outputs:=true \
  -p legacy_detection_topic:=/yolo/detections \
  -p legacy_image_topic:=/yolo/inference_image
'
```

This is the main deployment-oriented path:

- fine-tuned model
- corrected fast TensorRT engine
- ADAONE-compatible legacy outputs

## 5. Publish A Query

Host terminal:

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/CARKit/install/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic pub -1 /input_query std_msgs/msg/String "data: a chair, a person, a monitor, a bottle, a cup, a stop sign"
```

## 6. Indoor / Outdoor Scene Classification Test

This is the currently recommended validation flow for the scene-selection logic.

Important note:

- for this test, the most reliable path on this machine was a warmed-up baseline NanoOWL node on CPU inference
- the goal of this test is the scene-selection logic, not maximum throughput

Perception terminal:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
export PYTHONPATH=/workspaces/isaac_ros-dev/src/nanoowl:$PYTHONPATH
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run ros2_nanoowl nano_owl_py --ros-args \
  -r input_image:=/camera/camera/color/image_raw \
  -p model:=google/owlvit-base-patch32 \
  -p device:=cpu \
  -p thresholds:=0.05 \
  -p publish_output_image:=false \
  -p publish_legacy_outputs:=true \
  -p legacy_detection_topic:=/yolo/detections \
  -p legacy_image_topic:=/yolo/inference_image
'
```

Scene-manager terminal:

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/CARKit/install/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run ada scene_aware_query_manager --ros-args \
  -p startup_delay_sec:=1.0 \
  -p probe_duration_sec:=8.0 \
  -p probe_publish_period_sec:=1.0 \
  -p min_score_margin:=0.10
```

Watch the result:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /scene_mode
```

Useful extra watches:

```bash
ros2 topic echo /yolo/detections
ros2 topic echo /input_query
```

Latest confirmed result on this machine:

- scene mode locked to `indoor`
- scored decision: `indoor=2.28 (13 hits), outdoor=0.00 (0 hits)`

## 7. Current Scene Rules

Indoor probe defaults:

- `person`
- `people`
- `chair`
- `desk`
- `monitor`
- `bottle`
- `laptop`

Outdoor probe defaults:

- `pedestrian`
- `bicyclist`
- `bicycle`
- `motorcycle`
- `car`
- `truck`
- `bus`
- `stop sign`
- `traffic light`
- `cone`

Scene-neutral labels:

- `person`
- `people`
- `pedestrian`
- `pedestrians`
- `human`
- `humans`

Important:

- shared labels between indoor and outdoor probe lists are ignored for scene scoring
- scene-neutral labels are also ignored for scene scoring
- those labels can still remain in the final query sets for detection use

## 8. Quick Verification

Check the scene result:

```bash
ros2 topic echo /scene_mode --once
```

Check ADAONE-compatible detections:

```bash
ros2 topic echo /yolo/detections --once
```

Check NanoOWL-native detections from inside the container:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0
ros2 topic echo /output_detections --once
'
```

## 9. Stop Runtime Processes

Stop scene classification:

```bash
pkill -f scene_aware_query_manager || true
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc 'pkill -f nano_owl_py || true'
```

Stop the host ADAONE launch:

```bash
pkill -f "ros2 launch ada ada_system.launch.py" || true
```

Stop the Isaac container:

```bash
docker stop isaac_ros_dev-aarch64-container
```

Stop the F1TENTH low-level container:

```bash
docker rm -f f1tenth_container
```
