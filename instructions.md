# ROS2-NanoOWL Bring-Up Notes

This file records the exact process that worked in `/home/ada2/boyang_ws` so the same setup can be repeated on another Jetson without rediscovering the same failure modes.

## Environment That Worked

- Host OS: Ubuntu 22.04 on Jetson Orin
- ROS: Humble
- Workspace root: `/home/ada2/boyang_ws`
- Important source trees:
  - `src/isaac_ros_common`
  - `src/ROS2-NanoOWL`
  - `src/nanoowl`
  - `src/torch2trt`
- Base container image: `isaac_ros_dev-aarch64:latest`
- Saved working image: `isaac_ros_dev-aarch64:nanoowl-ready`

## Important Lessons

- `src/isaac_ros_common/scripts/run_dev.sh -d /home/ada2/boyang_ws` did not work here because `/home/ada2/boyang_ws` is not itself a Git repo.
- The reliable workaround was to create or reuse the Isaac ROS container directly with `docker run`, host networking, and the normal Isaac ROS entrypoint.
- The Isaac ROS image did not have a usable `torchvision` build for this Jetson and PyTorch combination, so `torchvision` had to be built from source inside the container.
- NanoOWL ONNX export needed `attn_implementation="eager"` to avoid the OWL-ViT SDPA export failure.
- The TensorRT engine build only succeeded after splitting ONNX export and `trtexec` into separate processes so Python-side GPU memory could be released first.
- The original live pipeline was too slow when it fell back to `device:=cpu`. The stable GPU path came back only after moving the heavyweight Hugging Face model work off the GPU and trimming repeated per-frame CPU work.
- The runbook now has two intentional runtime modes:
  - fast detection mode with `publish_output_image:=false`
  - visualization mode with `publish_output_image:=true`

## 1. Create Or Recreate The Isaac ROS Container

If you already have the saved working image, use that. Otherwise start from `isaac_ros_dev-aarch64:latest` and repeat the setup.

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
  isaac_ros_dev-aarch64:latest \
  /bin/bash -lc 'trap : TERM INT; sleep infinity & wait'
```

Verify the container workspace mount:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc 'printenv ISAAC_ROS_WS'
```

Expected output:

```text
/workspaces/isaac_ros-dev
```

## 2. Build A Working `torchvision` Inside The Container

Inside this Isaac ROS image, the bundled `torchvision` was not usable with the Jetson PyTorch build. The working fix was a source build copied into the user site-packages directory.

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

Why this exact flow:

- A normal pip wheel import worked only partially and failed at runtime because required ops were missing.
- Copying the source-built package tree worked immediately and was enough for NanoOWL.

## 3. Install Python Dependencies Inside The Container

Clean stale build artifacts first if earlier attempts left the wrong ownership behind:

```bash
docker exec -u root isaac_ros_dev-aarch64-container bash -lc '
chown -R 1000:1000 /home/admin/.local /workspaces/isaac_ros-dev/src/torch2trt /workspaces/isaac_ros-dev/src/nanoowl
rm -rf /workspaces/isaac_ros-dev/src/torch2trt/build
rm -rf /workspaces/isaac_ros-dev/src/torch2trt/torch2trt.egg-info
rm -rf /workspaces/isaac_ros-dev/src/nanoowl/build
rm -rf /workspaces/isaac_ros-dev/src/nanoowl/nanoowl.egg-info
'
```

Then install the missing Python dependencies as `admin`:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
python3 -m pip install --user transformers
cd /workspaces/isaac_ros-dev/src/torch2trt
python3 -m pip install --user --no-build-isolation .
cd /workspaces/isaac_ros-dev/src/nanoowl
python3 -m pip install --user --no-build-isolation .
python3 -c "import torch, torchvision, tensorrt; from nanoowl.owl_predictor import OwlPredictor; print(\"imports_ok\")"
'
```

## 4. Apply The Source Fixes That Were Needed

These edits are already present in this workspace.

### File: `src/nanoowl/nanoowl/owl_predictor.py`

- Load OWL-ViT with `attn_implementation="eager"` and fall back if that argument is unsupported.
- In `load_image_encoder_engine`, lazily create the TensorRT execution context if `TRTModule` did not create it during construction.
- When `image_encoder_engine` is used on `device:=cuda`, keep the full Hugging Face OWL-ViT model on CPU instead of on GPU.
- Keep text encoding on CPU in that TensorRT-backed mode and move only the text embeddings needed for decoding onto the image-embedding device.

Why:

- The eager-attention change avoids the ONNX export failure.
- The lazy-context change avoids the `'TRTModule' object has no attribute 'context'` crash.
- Keeping the Hugging Face model and text encoder on CPU frees Jetson GPU memory for the TensorRT image encoder, which made live GPU inference stable again.

### File: `src/ROS2-NanoOWL/ros2_nanoowl/nano_owl_py.py`

- Add a `device` ROS parameter.
- Only pass `image_encoder_engine` to `OwlPredictor` when `device == "cuda"`.
- Reduce the image subscription queue depth from `10` to `1`.
- Drop frames while a previous frame is still being processed.
- Cache query text encodings and only recompute them when the query changes.
- Add a `publish_output_image` parameter so annotated image drawing can be disabled for the fastest path.

Why:

- Query encoding on every frame was wasting time.
- Queue depth `1` plus frame dropping stops the node from processing stale frames forever.
- Disabling annotated image publishing removes unnecessary per-frame work when only detections matter.

## 5. How The Workload Shifted From CPU Back To GPU

The final speedup came from separating what really benefits from the Jetson GPU from what does not.

Before the fix:

- The TensorRT image encoder and the full Hugging Face OWL-ViT model were both competing for GPU memory.
- Query text encoding was being repeated on every frame even when the prompt did not change.
- Annotated image drawing and publishing ran even when only detections were needed.
- The ROS subscriber could queue stale frames faster than the node could process them.

After the fix:

- TensorRT image encoding stayed on the GPU.
- The Hugging Face model weights for text-side work stayed on CPU in TensorRT mode.
- Query embeddings were cached and reused until the query string changed.
- The subscriber queue was reduced to `1`, and incoming frames were dropped while busy.
- The fast runtime mode turned off `/output_image` publishing with `publish_output_image:=false`.

Observed effect on this machine:

- CPU fallback mode was much slower and felt laggy in live use.
- GPU fast mode reached about `10.3 Hz` on `/output_detections`.
- GPU visualization mode still held roughly `7 Hz` on `/output_image` and `8.4 Hz` on `/output_detections`.

## 6. Build The ROS Package

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash
cd /workspaces/isaac_ros-dev
colcon build --symlink-install --packages-select ros2_nanoowl
'
```

Verify the package import:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
python3 -c "import ros2_nanoowl.nano_owl_py; print(\"ros2_nanoowl_import_ok\")"
'
```

## 7. Generate The OWL-ViT TensorRT Engine

The one-shot NanoOWL builder held too much GPU memory while also calling `trtexec`. The reliable method was:

1. Export ONNX in one process.
2. Run `trtexec` in a second process.

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
cd /workspaces/isaac_ros-dev/src/nanoowl
python3 - <<'"'"'PY'"'"'
from nanoowl.owl_predictor import OwlPredictor
predictor = OwlPredictor(model_name="google/owlvit-base-patch32")
predictor.export_image_encoder_onnx("data/image_encoder.onnx", onnx_opset=16)
print("onnx_export_ok")
PY
/usr/src/tensorrt/bin/trtexec \
  --onnx=data/image_encoder.onnx \
  --saveEngine=data/owl_image_encoder_patch32.engine \
  --fp16 \
  --shapes=image:1x3x768x768
cp -f data/owl_image_encoder_patch32.engine /workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owl_image_encoder_patch32.engine
'
```

Final engine locations:

- `/home/ada2/boyang_ws/src/nanoowl/data/owl_image_encoder_patch32.engine`
- `/home/ada2/boyang_ws/src/ROS2-NanoOWL/data/owl_image_encoder_patch32.engine`

Git note:

- Each engine file is about `175 MB`, so do not commit it to a normal GitHub repo unless you intentionally use Git LFS. The normal path is to rebuild it locally with this section.

## 8. Smoke Test With The Sample Image

Use the sample image before touching the live camera.

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

Expected result:

- `/output_detections` publishes a `vision_msgs/msg/Detection2DArray`.

## 9. Live RealSense Camera Bring-Up

The RealSense node must run on the host. DDS communication between host and container was reliable only when both sides used:

- `RMW_IMPLEMENTATION=rmw_fastrtps_cpp`
- `ROS_LOCALHOST_ONLY=0`

Also, a lighter RealSense profile was more stable:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run realsense2_camera realsense2_camera_node --ros-args -p enable_depth:=false -p enable_infra1:=false -p enable_infra2:=false -p enable_gyro:=false -p enable_accel:=false
```

Fast GPU detection mode:

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

Visualization GPU mode:

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

Publish a prompt from the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic pub -1 /input_query std_msgs/msg/String "data: a person, a monitor, a chair"
```

Check detections from inside the container:

```bash
docker exec -it -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash &&
source /workspaces/isaac_ros-dev/install/setup.bash &&
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0 &&
ros2 topic echo /output_detections --once
'
```

RViz visualization from the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
rviz2
```

In RViz:

- Add an `Image` display.
- Set Topic to `/output_image`.
- If needed, set Reliability Policy to `Reliable`.

Host-side note:

- `ros2 topic echo /output_detections` on the host requires `vision_msgs` in the host ROS environment.
- If that package is missing, use the container echo command instead.

## 10. Verification Checklist

- `docker start isaac_ros_dev-aarch64-container` succeeds.
- `printenv ISAAC_ROS_WS` inside the container shows `/workspaces/isaac_ros-dev`.
- `python3 -c "import torch, torchvision, tensorrt"` works in the container.
- `from nanoowl.owl_predictor import OwlPredictor` works in the container.
- `colcon build --symlink-install --packages-select ros2_nanoowl` succeeds.
- The engine exists in both `src/nanoowl/data` and `src/ROS2-NanoOWL/data`.
- The sample-image path publishes `/output_detections`.
- The live-camera GPU path publishes `/output_detections`.
- Visualization mode publishes `/output_image`.

## 11. Troubleshooting

### `run_dev.sh` fails immediately

- Cause: the workspace root is not a Git repo.
- Fix: use the direct `docker run` command from section 1.

### `torchvision` imports but ops are missing

- Cause: incompatible prebuilt wheel.
- Fix: rebuild from source and copy `build/lib.linux-aarch64-cpython-310/torchvision` into `/home/admin/.local/lib/python3.10/site-packages`.

### ONNX export fails inside NanoOWL

- Cause: OWL-ViT attention implementation does not export cleanly.
- Fix: keep the `attn_implementation="eager"` patch in `owl_predictor.py`.

### Engine build fails with out-of-memory

- Cause: exporting ONNX and running `trtexec` in the same long-lived Python process keeps too much GPU memory resident.
- Fix: split ONNX export and `trtexec` into separate processes.

### GPU mode starts but RViz shows no image

- Cause: `publish_output_image:=false` was used.
- Fix: restart NanoOWL with `publish_output_image:=true` and subscribe to `/output_image` in RViz.

### GPU mode is running but feels slow again

- Cause: most often the node is in visualization mode, the query cache is not installed, or the GPU-friendly source patches are missing.
- Fix:
  - rebuild `ros2_nanoowl`
  - confirm the patched `owl_predictor.py` and `nano_owl_py.py` are installed
  - use the fast mode command with `publish_output_image:=false`
  - verify throughput with `ros2 topic hz /output_detections`

### `class_id` values in detections are numbers

- They are indexes into the query list in order.
- Example:
  - `0` means the first phrase in the query string.
  - `1` means the second phrase.
  - `2` means the third phrase.

## 12. Save The Working Container State

After the setup worked, the container was committed so the rebuilt Python environment could be reused:

```bash
docker commit isaac_ros_dev-aarch64-container isaac_ros_dev-aarch64:nanoowl-ready
```

If repeating this on another machine, do the same after the first successful bring-up to save time later.
