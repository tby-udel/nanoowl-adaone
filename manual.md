# ROS2-NanoOWL Manual

This is the current day-to-day runbook for the custom-model setup in `/home/ada2/boyang_ws`.

Everything in this file assumes NanoOWL is now using:

- model directory: `/workspaces/isaac_ros-dev/my_model`
- TensorRT engine: `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`

The old `google/owlvit-base-patch32` commands are intentionally not repeated here.

## 1. Required Files

These files should exist before launching:

- host model directory: `/home/ada2/boyang_ws/my_model`
- host engine file: `/home/ada2/boyang_ws/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`
- host backup engine copy: `/home/ada2/boyang_ws/src/nanoowl/data/my_model_image_encoder.engine`

Quick check:

```bash
ls -lh \
  /home/ada2/boyang_ws/my_model \
  /home/ada2/boyang_ws/src/ROS2-NanoOWL/data/my_model_image_encoder.engine \
  /home/ada2/boyang_ws/src/nanoowl/data/my_model_image_encoder.engine
```

## 2. Start The Container

If the saved container already exists:

```bash
docker start isaac_ros_dev-aarch64-container
```

If you need to recreate it from the saved image:

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

## 3. Verify The Runtime Before Launch

This confirms the container sees the workspace, the custom model, and the custom engine:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
printenv ISAAC_ROS_WS &&
ls -lh /workspaces/isaac_ros-dev/my_model &&
ls -lh /workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine
'
```

Expected highlights:

- `ISAAC_ROS_WS=/workspaces/isaac_ros-dev`
- `model.safetensors` is present in `/workspaces/isaac_ros-dev/my_model`
- `my_model_image_encoder.engine` exists in `src/ROS2-NanoOWL/data`

## 4. Sample-Image Smoke Test With The Custom Model

Use this before the camera if you want a quick end-to-end sanity check.

Terminal 1, publish the sample image:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
ros2 run image_publisher image_publisher_node /workspaces/isaac_ros-dev/src/nanoowl/assets/owl_glove_small.jpg --ros-args --remap /image_raw:=/input_image
'
```

Terminal 2, launch NanoOWL with the custom model and engine:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 run ros2_nanoowl nano_owl_py --ros-args \
  -p model:=/workspaces/isaac_ros-dev/my_model \
  -p device:=cuda \
  -p image_encoder_engine:=/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine \
  -p thresholds:=0.05 \
  -p publish_output_image:=true
'
```

Terminal 3, publish a query that matches the sample image:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
ros2 topic pub -1 /input_query std_msgs/msg/String "data: an owl, a glove"
'
```

Terminal 4, verify one detection message:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
ros2 topic echo /output_detections --once
'
```

Known good result from this workspace:

- sample-image inference with `my_model` returned `labels [0, 1]`
- sample-image inference with the custom TensorRT engine returned `num_boxes 2`

## 5. Live Camera Startup

Start the RealSense node on the host first.

Use the same ROS DDS settings on both host and container:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run realsense2_camera realsense2_camera_node --ros-args -p enable_depth:=false -p enable_infra1:=false -p enable_infra2:=false -p enable_gyro:=false -p enable_accel:=false
```

Success sign:

- the terminal prints `RealSense Node Is Up!`

## 6. Fast GPU Detection Mode With The Custom Model

Use this when you want detections only and do not need the annotated image topic.

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 run ros2_nanoowl nano_owl_py --ros-args \
  -r input_image:=/camera/camera/color/image_raw \
  -p model:=/workspaces/isaac_ros-dev/my_model \
  -p device:=cuda \
  -p image_encoder_engine:=/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine \
  -p thresholds:=0.05 \
  -p publish_output_image:=false
'
```

Important:

- `publish_output_image:=false` means `/output_image` will not publish frames.
- this is the preferred mode for throughput
- accuracy depends on what prompts your fine-tuned model was trained to handle

## 7. Visualization GPU Mode With The Custom Model

Use this when you want annotated frames for RViz or Foxglove.

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 run ros2_nanoowl nano_owl_py --ros-args \
  -r input_image:=/camera/camera/color/image_raw \
  -p model:=/workspaces/isaac_ros-dev/my_model \
  -p device:=cuda \
  -p image_encoder_engine:=/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine \
  -p thresholds:=0.05 \
  -p publish_output_image:=true
'
```

Important:

- use either fast mode or visualization mode, not both at once
- the correct visualization topic is `/output_image`

## 8. Publish A Query

From the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic pub -1 /input_query std_msgs/msg/String "data: a person, a monitor, a chair"
```

Model note:

- for best results, use prompts close to the classes or phrases your fine-tuned model saw during training
- `an owl, a glove` is only the smoke-test prompt for the bundled sample image

## 9. Check Detections

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

- `ros2 topic echo /output_detections` on the host requires `vision_msgs` in the host ROS installation
- if that package is missing on the host, use the container-side commands above

## 10. Visualize In RViz

Start RViz on the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
rviz2
```

Inside RViz:

- add an `Image` display
- set Topic to `/output_image`
- if the view is blank, set Reliability Policy to `Reliable`

Quick one-shot image check:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic echo /output_image --once
```

## 11. Rebuild The Custom TensorRT Engine If Needed

This is the exact command sequence that finally succeeded on this Jetson.

Important prerequisites:

- reboot the Jetson first
- do not start RealSense, RViz, NanoOWL, or other GPU-heavy tasks before running it
- run it early after boot while memory is still clean

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
source /opt/ros/humble/setup.bash
cd /workspaces/isaac_ros-dev/src/nanoowl
rm -f data/my_model_image_encoder_opset17.onnx data/my_model_image_encoder.engine data/patch32_orin.timing
python3 - <<'"'"'PY'"'"'
from nanoowl.owl_predictor import OwlPredictor
predictor = OwlPredictor(model_name="/workspaces/isaac_ros-dev/my_model", device="cpu")
predictor.export_image_encoder_onnx("data/my_model_image_encoder_opset17.onnx", onnx_opset=17)
print("onnx17_export_ok")
PY
/usr/src/tensorrt/bin/trtexec \
  --onnx=data/my_model_image_encoder_opset17.onnx \
  --saveEngine=data/my_model_image_encoder.engine \
  --fp16 \
  --shapes=image:1x3x768x768 \
  --builderOptimizationLevel=0 \
  --maxAuxStreams=0 \
  --tacticSources=-CUDNN,-EDGE_MASK_CONVOLUTIONS,-JIT_CONVOLUTIONS \
  --timingCacheFile=data/patch32_orin.timing \
  --skipInference
cp -f data/my_model_image_encoder.engine /workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine
ls -lh data/my_model_image_encoder.engine /workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine data/patch32_orin.timing
'
```

What this does:

- exports the custom model to ONNX with opset `17`
- builds the TensorRT engine with a low-memory builder configuration
- writes a timing cache to `src/nanoowl/data/patch32_orin.timing`
- copies the finished engine to the ROS package data directory

Successful output highlights from this workspace:

- engine generation completed in about `41.5 seconds`
- engine size was about `173 MiB`
- timing cache size was about `351 KiB`

## 12. If The Engine File Is Missing

The ROS node now falls back to direct model inference instead of crashing if the engine path does not exist.

That fallback is useful for debugging, but it is not the preferred runtime on this Jetson:

- direct CPU mode works but is slower
- direct GPU mode without TensorRT was unstable under memory pressure
- the custom TensorRT engine is the intended deployment path

## 13. Useful Checks

Confirm camera topics on the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic list | grep '^/camera/'
```

Confirm NanoOWL is in the ROS graph:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 node list
'
```

Confirm output topics exist:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 topic list | grep -E "^/output_detections$|^/output_image$|^/input_query$"
'
```

Confirm `output_detections` publisher state:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 topic info /output_detections -v
'
```

## 14. Shutdown

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
