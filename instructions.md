# ADAONE + NanoOWL End-To-End Instructions

This file is the practical end-to-end runbook for this machine and this workspace.

It is intentionally code-heavy.

It covers:

- install and build assumptions
- NanoOWL container setup
- corrected TensorRT engine build
- CARKit, sensor, and F1TENTH bring-up
- proper low-level wheel-driver bring-up through `ada_system`
- scene-aware indoor/outdoor testing
- safe final launch of the vehicle-side stack plus NanoOWL
- generated helper scripts to launch and stop everything

## Safety First

The launch flow below is a safe bring-up flow, not a full autonomous driving flow.

What it does launch:

- F1TENTH low-level stack
- RealSense
- LiDAR
- LiDAR transformer
- LiDAR localization
- control center
- depth-based object position
- NanoOWL on GPU

What it does **not** launch:

- pure pursuit
- waypoint following
- any explicit autonomous motion publisher

Important note:

- keep the joystick centered and do not enable autonomous control while testing
- the goal here is bring-up and perception integration, not vehicle motion
- when `control_center_node` is active, upstream drive-path tests should go through `/purepursuit_cmd`, not direct `/ackermann_cmd`
- scene classification should not use shared or scene-neutral human labels to decide `indoor` vs `outdoor`

## Known-Good Local Paths

These instructions assume the following paths already exist on the machine:

- NanoOWL workspace:
  - `/home/ada2/boyang_ws`
- CARKit workspace:
  - `/home/ada2/CARKit`
- sensor workspace:
  - `/home/ada2/sensor_ws`
- F1TENTH Foxy container workspace:
  - `/home/ada2/ada_system`

Important runtime assets:

- fine-tuned model:
  - `/home/ada2/boyang_ws/models/owlvit_deal_imagenet_step55_hf`
- corrected fast TensorRT engine:
  - `/home/ada2/boyang_ws/src/nanoowl/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`
- ROS-visible engine copy:
  - `/home/ada2/boyang_ws/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`

## 1. Required Docker Images

Verify or pull the images used by the current workflow:

```bash
docker pull ariiees/ada:foxy-f1tenth
docker images | grep -E 'ariiees/ada|isaac_ros_dev-aarch64'
```

Known-good local images on this machine:

- `ariiees/ada:foxy-f1tenth`
- `isaac_ros_dev-aarch64:latest`
- `isaac_ros_dev-aarch64:nanoowl-ready`

## 2. Build The Host ROS Workspaces

### 2.1 Build `sensor_ws`

This workspace provides:

- `realsense2_camera`
- `sllidar_ros2`

```bash
cd /home/ada2/sensor_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

### 2.2 Build `CARKit`

This workspace provides:

- `ada`
- `control_center`
- `util`
- `lidar_localization_ros2`

```bash
cd /home/ada2/CARKit
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
colcon build --symlink-install
```

Quick check:

```bash
test -f /home/ada2/CARKit/install/setup.bash && echo CARKIT_OK
test -f /home/ada2/sensor_ws/install/setup.bash && echo SENSOR_WS_OK
```

## 3. Create Or Reuse The Isaac ROS NanoOWL Container

If the working container already exists, reuse it.

Create it if needed:

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

Start it:

```bash
docker start isaac_ros_dev-aarch64-container
```

Verify:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc 'printenv ISAAC_ROS_WS'
```

Expected:

```text
/workspaces/isaac_ros-dev
```

## 4. Install NanoOWL Python Dependencies Inside The Container

If this is a fresh container and not the prepared `nanoowl-ready` image, run:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
python3 -m pip install --user transformers pycocotools
cd /workspaces/isaac_ros-dev/src/torch2trt
python3 -m pip install --user --no-build-isolation .
cd /workspaces/isaac_ros-dev/src/nanoowl
python3 -m pip install --user --no-build-isolation .
python3 -c "import torch, torchvision, tensorrt; from nanoowl.owl_predictor import OwlPredictor; print(\"imports_ok\")"
'
```

If `torchvision` is broken in the container, rebuild it from source:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
rm -rf /tmp/vision
git clone --branch v0.20.0 --depth 1 https://github.com/pytorch/vision.git /tmp/vision
cd /tmp/vision
python3 setup.py build
mkdir -p /home/admin/.local/lib/python3.10/site-packages
rm -rf /home/admin/.local/lib/python3.10/site-packages/torchvision
cp -a build/lib.linux-aarch64-cpython-310/torchvision /home/admin/.local/lib/python3.10/site-packages/
python3 -c "import torchvision; from torchvision.ops import roi_align; print(torchvision.__version__)"
'
```

## 5. Build NanoOWL And `ros2_nanoowl`

Reinstall the Python package and rebuild the ROS package:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
source /opt/ros/humble/setup.bash
cd /workspaces/isaac_ros-dev/src/nanoowl
python3 -m pip install --user --no-build-isolation .
cd /workspaces/isaac_ros-dev
colcon build --symlink-install --packages-select ros2_nanoowl
'
```

## 6. Build The Corrected Fast Fine-Tuned TensorRT Engine

This is the current recommended engine build path.

It uses:

- the fine-tuned checkpoint
- a stock-style TensorRT builder path
- ONNX opset `17`

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
source /opt/ros/humble/setup.bash
cd /workspaces/isaac_ros-dev/src/nanoowl
rm -f data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.onnx
rm -f data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine
python3 - <<'"'"'PY'"'"'
from nanoowl.owl_predictor import OwlPredictor
predictor = OwlPredictor(
    model_name="/workspaces/isaac_ros-dev/models/owlvit_deal_imagenet_step55_hf",
    device="cpu",
)
predictor.export_image_encoder_onnx(
    "data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.onnx",
    onnx_opset=17,
)
print("onnx17_export_ok")
PY
/usr/src/tensorrt/bin/trtexec \
  --onnx=data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.onnx \
  --saveEngine=data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine \
  --fp16 \
  --shapes=image:1x3x768x768
cp -f data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine \
  /workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine
ls -lh \
  data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine \
  /workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine
'
```

## 7. Current NanoOWL Default Runtime

The current source defaults are already set to:

- model:
  - `/workspaces/isaac_ros-dev/models/owlvit_deal_imagenet_step55_hf`
- engine:
  - `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`

The most important ROS runtime flags for ADAONE integration are:

- `device:=cuda`
- `publish_output_image:=false`
- `publish_legacy_outputs:=true`
- remap input image to:
  - `/camera/camera/color/image_raw`

That last flag matters because `publish_legacy_outputs:=true` is what lets NanoOWL feed the existing ADAONE `/yolo/detections` consumer path.

## 8. Manual Safe Launch By Hand

This is the manual version of the full safe bring-up.

### 8.1 Start The Isaac ROS Container

```bash
docker start isaac_ros_dev-aarch64-container
```

### 8.2 Terminal 1: Start The F1TENTH Foxy Container The Proper Way

```bash
cd /home/ada2/ada_system
./run_container.sh
```

Important note:

- this is the workflow that finally produced real wheel motion on this machine
- the lower-chassis stack should be launched from the interactive `ada_system` container, not from a stale partial setup

### 8.3 Inside The `ada_system` Container: F1TENTH Bring-Up

```bash
source install_foxy/setup.bash
ros2 launch f1tenth_stack bringup_launch.py
```

Important note:

- `install/setup.bash` was stale for the low-level stack on this machine
- `install_foxy/setup.bash` is the correct environment for `f1tenth_stack`, `vesc_driver`, and `vesc_ackermann`
- the working VESC config on this machine used `/dev/ttyACM0`

### 8.4 Terminal 2: LiDAR

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 launch sllidar_ros2 sllidar_s2_launch.py
```

### 8.5 Terminal 3: RealSense Low-Load Profile

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 launch realsense2_camera rs_launch.py \
  enable_color:=true \
  enable_depth:=true \
  enable_rgbd:=true \
  align_depth.enable:=true \
  enable_sync:=true \
  enable_gyro:=false \
  enable_accel:=false \
  enable_infra1:=false \
  enable_infra2:=false \
  rgb_camera.color_profile:=640,480,15 \
  depth_module.depth_profile:=640,480,15
```

### 8.6 Terminal 4: LiDAR Transformer

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run util lidar_transformer_node
```

### 8.7 Terminal 5: LiDAR Localization

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 launch lidar_localization_ros2 lidar_localization.launch.py
```

### 8.8 Terminal 6: Control Center

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run control_center control_center_node
```

### 8.9 Terminal 7: Object Position

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run ada object_position --ros-args -p target_object_type:=chair
```

### 8.10 Terminal 8: NanoOWL On GPU

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
  -p publish_legacy_outputs:=true
'
```

### 8.11 Terminal 9: Publish A Query

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic pub -1 /input_query std_msgs/msg/String "data: a chair, a person, a monitor, a bottle, a cup, a stop sign"
```

### 8.12 Indoor / Outdoor Scene Classification Test Only

This is the lightest recordable scene-selection test. It does not require changing the control logic.

Important note:

- on this Jetson, the most reliable validation path used a warmed-up baseline NanoOWL node on CPU inference
- the fine-tuned TensorRT path is still the recommended deployment target overall, but it was not the most stable path for the scene-classification test under a loaded ADAONE stack

Terminal A, start a perception-only NanoOWL node:

```bash
docker start isaac_ros_dev-aarch64-container
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

Terminal B, run the scene-aware query manager:

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run ada scene_aware_query_manager --ros-args \
  -p startup_delay_sec:=1.0 \
  -p probe_duration_sec:=8.0 \
  -p probe_publish_period_sec:=1.0 \
  -p min_score_margin:=0.10
```

Terminal C, watch the result:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /scene_mode
```

Optional visibility:

```bash
ros2 topic echo /yolo/detections
ros2 topic echo /input_query
```

Latest confirmed result on this machine:

- scene mode locked to `indoor`
- the scored decision was `indoor=2.28 (13 hits), outdoor=0.00 (0 hits)`
- the indoor vote was driven by detections like `bottle`, `chair`, and `box`

Classification rule:

- labels shared by both probe lists are ignored
- scene-neutral human-family labels are also ignored for scoring:
  - `person`
  - `people`
  - `pedestrian`
  - `pedestrians`
  - `human`
  - `humans`

## 9. One-Command Safe Launcher

Generated scripts:

- `scripts/launch_adaone_nanoowl_safe.sh`
- `scripts/stop_adaone_nanoowl_safe.sh`

Default behavior of the launcher:

- starts the F1TENTH container in detached mode
- starts the Isaac ROS NanoOWL container
- launches the safe host stack in the background
- launches NanoOWL on GPU
- publishes a default query once
- stores logs under:
  - `/home/ada2/boyang_ws/runtime/adaone_nanoowl/latest`

### 9.1 Launch Everything

```bash
cd /home/ada2/boyang_ws
./scripts/launch_adaone_nanoowl_safe.sh
```

### 9.2 Launch With A Custom Query And Target Object

```bash
cd /home/ada2/boyang_ws
./scripts/launch_adaone_nanoowl_safe.sh \
  --target-object-type chair \
  --query "a chair, a person, a monitor, a bottle, a cup, a stop sign"
```

### 9.3 Optional Flags

```bash
./scripts/launch_adaone_nanoowl_safe.sh --help
```

Supported options:

- `--target-object-type <label>`
- `--query "<comma separated prompt list>"`
- `--threshold <float>`
- `--publish-output-image`
- `--no-lidar-localization`

## 10. Verification Commands

### 10.1 ROS Graph

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 node list
```

Expected important nodes:

- `/camera/camera`
- `/nano_owl_subscriber`
- `/object_position_node`
- `/control_center_node`
- `/lidar_transformer_node`
- `/lidar_localization`

### 10.2 NanoOWL Detections

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic hz /output_detections
```

### 10.3 ADAONE-Compatible Detection Stream

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /yolo/detections --once
```

### 10.4 Depth-Based Object Position

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /object_position --once
```

### 10.5 Confirm Safe Stop-State Command

```bash
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
source /home/ada2/CARKit/install/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /ackermann_cmd --once
```

Expected safe behavior:

- no pure pursuit node is active
- no autonomy enable command is sent
- `speed` should stay at `0.0` in the idle safe bring-up

## 11. Stop Everything

Stop with the generated helper:

```bash
cd /home/ada2/boyang_ws
./scripts/stop_adaone_nanoowl_safe.sh
```

## 12. Troubleshooting

### NanoOWL Falls Back To CPU

Check:

```bash
ls -lh /home/ada2/boyang_ws/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine
```

If the engine is missing, rebuild it using section `6`.

### LiDAR Does Not Start

Retry permission fix:

```bash
docker exec f1tenth_container chmod 777 /dev/ttyUSB0 >/dev/null 2>&1 || true
docker exec f1tenth_container chmod 777 /dev/ttyACM0 >/dev/null 2>&1 || true
```

If the wheel driver is the actual problem rather than LiDAR:

- verify the low-level stack was launched from `/home/ada2/ada_system/run_container.sh`
- verify `source install_foxy/setup.bash` was used inside the container
- verify the active VESC serial path is correct for the current machine state
- on this ADAONE, the successful wheel-motion test used `/dev/ttyACM0`

### NanoOWL Starts But No ADAONE Detections Flow

Check:

```bash
ros2 topic echo /yolo/detections --once
ros2 topic echo /output_detections --once
```

If `/output_detections` exists but `/yolo/detections` is empty, make sure NanoOWL was launched with:

- `-p publish_legacy_outputs:=true`

If the scene selector falls back with zero scores:

- let NanoOWL warm up first
- rerun `scene_aware_query_manager` after NanoOWL is already alive
- use the lighter baseline CPU path for the scene test if the TensorRT/GPU path is unstable on the loaded stack

### RealSense Is Too Heavy

Keep the reduced profile:

- `rgb_camera.color_profile:=640,480,15`
- `depth_module.depth_profile:=640,480,15`

### The Whole Stack Feels Slow

Keep these settings:

- `device:=cuda`
- TensorRT engine enabled
- `publish_output_image:=false`

## 13. Current Bottom Line

The current known-good deployment on this machine is:

- fine-tuned model:
  - `/workspaces/isaac_ros-dev/models/owlvit_deal_imagenet_step55_hf`
- corrected fast TensorRT engine:
  - `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`
- safe integrated stack:
  - F1TENTH bring-up
  - LiDAR
  - RealSense
  - LiDAR localization
  - control center
  - object position
  - NanoOWL on GPU
- scene-aware indoor/outdoor demo:
  - camera input
  - NanoOWL legacy detections
  - `scene_aware_query_manager`
  - shared labels and human-family labels excluded from scene scoring

This is the current recommended way to launch ADAONE together with the NanoOWL perception module on this Jetson.
