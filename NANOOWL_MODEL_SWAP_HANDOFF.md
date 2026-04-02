# NanoOWL Custom Model Swap Handoff

## Current Status

This handoff is no longer a proposal. The custom-model swap has been implemented in the current workspace.

Current state:

- NanoOWL no longer depends on the stock `google/owlvit-base-patch32` path for normal operation.
- The workspace now uses the uploaded local Hugging Face model directory at `/home/ada2/boyang_ws/my_model`.
- A matching TensorRT image encoder engine has been built successfully on this Jetson.
- The ROS node has been launched with the custom model and the custom engine.

## Final Goal

Replace NanoOWL's default `google/owlvit-base-patch32` with our fine-tuned OWL-ViT model while keeping the rest of the NanoOWL and ROS 2 pipeline as unchanged as possible.

That goal is now achieved in this workspace.

## Custom Model Folder In This Workspace

The active model directory is:

`/home/ada2/boyang_ws/my_model`

This directory contains a Hugging Face-compatible checkpoint:

- `config.json`
- `model.safetensors`
- `processor_config.json`
- `tokenizer.json`
- `tokenizer_config.json`

Do not split these files. Keep them together in one directory.

## Final Integration Strategy That Was Used

Use the fine-tuned model as a local Hugging Face model directory.

This was the lowest-risk approach because NanoOWL already uses:

- `OwlViTForObjectDetection.from_pretrained(model_name)`
- `OwlViTProcessor.from_pretrained(model_name)`

Both functions support loading from a local directory, so the key work was compatibility and engine rebuild, not a wholesale model-wrapper rewrite.

## What Was Changed In Code

### `src/nanoowl/nanoowl/owl_predictor.py`

Implemented:

1. Local-directory support for model metadata

- If `model_name` is a local directory, NanoOWL now reads:
  - `vision_config.image_size`
  - `vision_config.patch_size`
  from `config.json`

2. Processor behavior

- `OwlViTProcessor.from_pretrained(model_name, use_fast=False)` is now used.

3. Existing Jetson/TensorRT fixes were preserved

- `attn_implementation="eager"` on model load
- lazy TensorRT execution-context creation
- CPU text side plus GPU TensorRT image side when using the engine

Why:

- the original code hardcoded image size and patch size by official model-name string
- that failed for a local path like `/workspaces/isaac_ros-dev/my_model`
- the `use_fast=False` choice keeps deployment tokenization closer to the safer PIL-backed path

### `src/ROS2-NanoOWL/ros2_nanoowl/nano_owl_py.py`

Implemented:

- default `model` parameter now points to `/workspaces/isaac_ros-dev/my_model`
- default `image_encoder_engine` parameter now points to `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`
- if the engine file is missing, the node now warns and falls back to direct model inference instead of crashing

Existing performance fixes remained in place:

- `device` parameter
- query-embedding cache
- queue depth `1`
- frame dropping while busy
- optional `publish_output_image`

### `src/ROS2-NanoOWL/launch/nano_owl_example.launch.py`

Implemented:

- default `model` launch argument now points to `/workspaces/isaac_ros-dev/my_model`
- default `image_encoder_engine` launch argument now points to `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`

### `src/ROS2-NanoOWL/launch/camera_input_example.launch.py`

Implemented:

- same default custom model path
- same default custom engine path

## Why The Engine Had To Be Rebuilt

The TensorRT engine contains the image encoder weights.

Because the model was fine-tuned, the old stock engine built from `google/owlvit-base-patch32` could not be reused.

The custom checkpoint required its own matching engine.

## Custom Engine Files

Final engine locations:

- `/home/ada2/boyang_ws/src/nanoowl/data/my_model_image_encoder.engine`
- `/home/ada2/boyang_ws/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`

Timing cache created during the successful build:

- `/home/ada2/boyang_ws/src/nanoowl/data/patch32_orin.timing`

Approximate sizes from the successful run:

- `model.safetensors`: `585 MiB`
- `my_model_image_encoder.engine`: `174 MiB`
- `patch32_orin.timing`: `351 KiB`

## What Initially Failed

The custom engine did not build successfully on the first attempts.

Observed behavior:

- ONNX export succeeded
- TensorRT parsed the model successfully
- TensorRT then ran out of GPU memory during tactic selection
- TensorRT eventually reported it could not find an implementation for a `ForeignNode`

Important interpretation:

- the ONNX graph was not the root problem
- the underlying issue was Jetson memory pressure during tactic search

## What Finally Worked

The successful engine build needed these conditions:

1. reboot the Jetson first
2. keep the system idle before running `trtexec`
3. export ONNX with opset `17`
4. build the engine with a lower-memory TensorRT configuration
5. save a timing cache

Exact successful build command:

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
'
```

Notable detail from the successful run:

- TensorRT still printed some OOM warnings while rejecting expensive tactics
- despite that, it found a valid implementation set and completed engine generation

Successful build summary:

- engine generation completed in about `41.5 seconds`
- engine size was about `173 MiB`
- timing cache recorded about `150` timing entries

## What Was Verified After The Build

### Predictor-Level Verification

Custom model loaded successfully:

- `image_size 768`
- `patch_size 32`

Sample-image test with the custom model:

- `labels [0, 1]`
- `num_boxes 2`

Sample-image test with the custom TensorRT engine:

- `labels [0, 1]`
- `num_boxes 2`

### ROS-Level Verification

The ROS node launched successfully with:

- model: `/workspaces/isaac_ros-dev/my_model`
- engine: `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`

Confirmed ROS graph result:

- `/nano_owl_subscriber` appeared in `ros2 node list`

## Final Launch Command

This is the exact explicit launch command for the custom model and engine:

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

## RealSense Bring-Up Command

Run this on the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run realsense2_camera realsense2_camera_node --ros-args -p enable_depth:=false -p enable_infra1:=false -p enable_infra2:=false -p enable_gyro:=false -p enable_accel:=false
```

## Query Command

Run this on the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic pub -1 /input_query std_msgs/msg/String "data: a person, a monitor, a chair"
```

Model note:

- detection quality now depends on what the fine-tuned checkpoint was trained for
- use prompts that match the custom model's domain

## Recommendation For Future Rebuilds

If the engine must be rebuilt:

1. reboot first
2. do not start RealSense, RViz, or NanoOWL before the build
3. reuse the exact successful command above
4. keep the generated timing cache file

## If The Engine Is Missing

Current behavior:

- the ROS node logs a warning
- the node falls back to direct model inference

This is useful for debugging, but the intended deployment path is the custom TensorRT engine.

## Portability Note

The final engine should be built on the Jetson target or a closely matching Jetson environment, not on an unrelated stronger non-Jetson machine.

Reason:

- TensorRT engines are platform-sensitive
- JetPack does not provide the broad portability path that would make an arbitrary x86-built engine the safe deployment artifact here

## Summary

The final deployment path in this workspace is now:

1. keep the fine-tuned model folder in `/home/ada2/boyang_ws/my_model`
2. use the patched NanoOWL source already present in this workspace
3. use the rebuilt custom TensorRT engine at `src/ROS2-NanoOWL/data/my_model_image_encoder.engine`
4. launch NanoOWL with the explicit custom model and custom engine paths

The original design goal was to keep NanoOWL almost unchanged while swapping in the fine-tuned model. That is exactly what was done.
