# ROS2-NanoOWL Bring-Up Notes

This file records the exact process that worked in `/home/ada2/boyang_ws` so the same custom-model setup can be repeated on another Jetson without rediscovering the same failure modes.

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
- Active custom model directory: `/home/ada2/boyang_ws/my_model`
- Active custom ROS engine path: `/home/ada2/boyang_ws/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`
- Active backup engine path: `/home/ada2/boyang_ws/src/nanoowl/data/my_model_image_encoder.engine`

## Final Outcome

The model swap is complete.

NanoOWL now uses our fine-tuned OWL-ViT checkpoint instead of the stock `google/owlvit-base-patch32` path.

Verified working pieces:

- the custom Hugging Face model directory loads in the container
- NanoOWL reads `image_size` and `patch_size` from the local `config.json`
- `ros2_nanoowl` now defaults to the custom model and custom engine path
- the custom TensorRT engine was successfully built on this Jetson after reboot
- direct sample-image inference with the custom model and custom engine succeeded
- the ROS node launched successfully with the custom model and custom engine

## Important Lessons

- `src/isaac_ros_common/scripts/run_dev.sh -d /home/ada2/boyang_ws` did not work here because `/home/ada2/boyang_ws` is not itself a Git repo.
- The reliable workaround was to create or reuse the Isaac ROS container directly with `docker run`, host networking, and the normal Isaac ROS entrypoint.
- The Isaac ROS image did not have a usable `torchvision` build for this Jetson and PyTorch combination, so `torchvision` had to be built from source inside the container.
- NanoOWL ONNX export needed `attn_implementation="eager"` to avoid the OWL-ViT SDPA export failure.
- The TensorRT engine build only became reliable after separating ONNX export from `trtexec`.
- The custom engine did not build reliably while the Jetson was in a fragmented memory state. A reboot plus a lower-memory builder configuration was required.
- TensorRT may still print OOM warnings while rejecting some tactics. That does not necessarily mean the final build failed. In the successful run here, TensorRT skipped some tactics and still completed engine generation.

## 1. Create Or Recreate The Isaac ROS Container

If the saved working image already exists, reuse it. Otherwise start from `isaac_ros_dev-aarch64:latest`.

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

Verify the workspace mount:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc 'printenv ISAAC_ROS_WS'
```

Expected:

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

- a regular pip wheel import worked only partially and failed at runtime because compiled ops were missing
- copying the source-built package tree worked immediately and was enough for NanoOWL

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

Then install the missing Python dependencies:

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

## 4. Upload The Fine-Tuned Model Folder

The custom model is stored directly in the workspace root:

- `/home/ada2/boyang_ws/my_model`

Files currently present:

- `config.json`
- `model.safetensors`
- `processor_config.json`
- `tokenizer.json`
- `tokenizer_config.json`

Do not split these files. The model directory must remain intact so Hugging Face can load it as a local checkpoint.

Quick check:

```bash
ls -lh /home/ada2/boyang_ws/my_model
```

## 5. Patch NanoOWL To Accept A Local Hugging Face Directory

These edits are already present in this workspace.

### File: `src/nanoowl/nanoowl/owl_predictor.py`

Implemented changes:

- import `json`
- if `model_name` is a local directory, read `vision_config.image_size` from `config.json`
- if `model_name` is a local directory, read `vision_config.patch_size` from `config.json`
- keep the stock hardcoded table for official Google model names
- load the processor with `use_fast=False`
- keep the earlier Jetson-specific TensorRT fixes:
  - eager attention for OWL-ViT load
  - lazy TensorRT execution context creation
  - keep the full Hugging Face model on CPU when TensorRT image encoding is used
  - move only the needed text embeddings to the image device during decode

Why:

- local model directories do not match the original string-based lookup logic
- `use_fast=False` reduces the chance of tokenization differences relative to training-time preprocessing
- the earlier CPU/GPU split is still required to keep the Jetson GPU path stable

### File: `src/ROS2-NanoOWL/ros2_nanoowl/nano_owl_py.py`

Implemented changes:

- default model parameter now points to `/workspaces/isaac_ros-dev/my_model`
- default engine parameter now points to `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`
- if the engine path is missing, log a warning and fall back to direct model inference
- preserve earlier performance fixes:
  - `device` parameter
  - queue depth `1`
  - frame dropping while busy
  - cached text encodings
  - optional `publish_output_image`

Why:

- the ROS node now uses the custom model and engine by default
- the fallback avoids a hard crash if the engine file is temporarily missing during rebuilds

### File: `src/ROS2-NanoOWL/launch/nano_owl_example.launch.py`

Implemented changes:

- default `model` launch argument now points to `/workspaces/isaac_ros-dev/my_model`
- default `image_encoder_engine` launch argument now points to `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`

### File: `src/ROS2-NanoOWL/launch/camera_input_example.launch.py`

Implemented changes:

- same default custom model path
- same default custom engine path

## 6. Reinstall NanoOWL And Rebuild The ROS Package

After changing the code, reinstall the Python package:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
source /opt/ros/humble/setup.bash
cd /workspaces/isaac_ros-dev/src/nanoowl
python3 -m pip install --user --no-build-isolation .
'
```

Then rebuild `ros2_nanoowl`:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
source /opt/ros/humble/setup.bash
cd /workspaces/isaac_ros-dev
colcon build --symlink-install --packages-select ros2_nanoowl
'
```

## 7. Validate The Local Model Before Building TensorRT

This checks that the custom directory loads correctly even before the engine exists:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
source /opt/ros/humble/setup.bash
cd /workspaces/isaac_ros-dev/src/nanoowl
python3 - <<'"'"'PY'"'"'
from nanoowl.owl_predictor import OwlPredictor
predictor = OwlPredictor(model_name="/workspaces/isaac_ros-dev/my_model", device="cpu")
print("image_size", predictor.image_size)
print("patch_size", predictor.patch_size)
print("processor_ok")
PY
'
```

Known good result from this workspace:

- `image_size 768`
- `patch_size 32`
- `processor_ok`

## 8. Validate The Custom Model With A CPU Smoke Test

This uses the bundled sample image only to confirm the model path and NanoOWL pipeline work end to end.

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
python3 - <<'"'"'PY'"'"'
from nanoowl.owl_predictor import OwlPredictor
from PIL import Image
predictor = OwlPredictor(model_name="/workspaces/isaac_ros-dev/my_model", device="cpu")
img = Image.open("/workspaces/isaac_ros-dev/src/nanoowl/assets/owl_glove_small.jpg").convert("RGB")
text = ["an owl", "a glove"]
enc = predictor.encode_text(text)
out = predictor.predict(image=img, text=text, text_encodings=enc, threshold=[0.05, 0.05], pad_square=False)
print("labels", out.labels.tolist())
print("num_boxes", len(out.boxes))
PY
'
```

Known good result:

- `labels [0, 1]`
- `num_boxes 2`

## 9. Why The First Custom TensorRT Builds Failed

The failure was not a model-format problem. ONNX export worked every time.

The real problem was Jetson GPU memory pressure during TensorRT tactic selection.

Observed failure pattern:

- `trtexec` parsed the ONNX model correctly
- TensorRT started tactic search
- one or more tactics requested an additional `~174 MB` or `~348 MB`
- the allocator failed
- TensorRT eventually reported:
  - `Could not find any implementation for node {ForeignNode[/vision_model/embeddings/.../Concat]}`

Important detail:

- that final graph error was downstream of tactic exhaustion
- it did not mean the ONNX graph itself was invalid

What did not solve it by itself:

- using the same exact build method that worked earlier for the stock model
- lowering `builderOptimizationLevel` alone
- setting `maxAuxStreams=0` alone
- trimming tactic sources alone
- using opset `17` alone

## 10. What Finally Made The Custom Engine Build Work

The successful engine build needed all of the following together:

1. reboot the Jetson first
2. do not launch RealSense, RViz, NanoOWL, or other GPU-heavy tasks before the build
3. export ONNX with opset `17`
4. use a low-memory TensorRT builder configuration
5. save a timing cache file for future rebuilds

Successful command:

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

Why this worked:

- opset `17` produced a cleaner export for TensorRT
- `builderOptimizationLevel=0` reduced builder search pressure
- `maxAuxStreams=0` reduced memory overhead
- removing `CUDNN`, `EDGE_MASK_CONVOLUTIONS`, and `JIT_CONVOLUTIONS` reduced the tactic pool
- `--skipInference` avoided the post-build benchmark pass
- the reboot gave TensorRT a cleaner memory state to start from

Successful build output from this workspace:

- TensorRT still reported some OOM warnings while rejecting high-memory tactics
- despite those warnings, TensorRT continued and found a valid implementation set
- engine generation completed in about `41.5 seconds`
- engine size was about `173 MiB`
- timing cache size was about `351 KiB`

Final files created:

- `/home/ada2/boyang_ws/src/nanoowl/data/my_model_image_encoder.engine`
- `/home/ada2/boyang_ws/src/ROS2-NanoOWL/data/my_model_image_encoder.engine`
- `/home/ada2/boyang_ws/src/nanoowl/data/patch32_orin.timing`

## 11. Validate The Custom Engine

After the engine is built, verify that NanoOWL can use it:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
set -e
source /opt/ros/humble/setup.bash
source /workspaces/isaac_ros-dev/install/setup.bash
python3 - <<'"'"'PY'"'"'
from nanoowl.owl_predictor import OwlPredictor
from PIL import Image
predictor = OwlPredictor(
    model_name="/workspaces/isaac_ros-dev/my_model",
    device="cuda",
    image_encoder_engine="/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/my_model_image_encoder.engine",
)
img = Image.open("/workspaces/isaac_ros-dev/src/nanoowl/assets/owl_glove_small.jpg").convert("RGB")
text = ["an owl", "a glove"]
enc = predictor.encode_text(text)
out = predictor.predict(image=img, text=text, text_encodings=enc, threshold=[0.05, 0.05], pad_square=False)
print("labels", out.labels.tolist())
print("num_boxes", len(out.boxes))
PY
'
```

Known good result:

- `labels [0, 1]`
- `num_boxes 2`

## 12. Launch The ROS Node With The Custom Model And Engine

The ROS node can now be launched directly with the custom assets:

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

Known good ROS graph result:

- `/nano_owl_subscriber` appeared in `ros2 node list`

## 13. RealSense Host Bring-Up

The RealSense node must run on the host, not inside the container.

Use these host settings:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 run realsense2_camera realsense2_camera_node --ros-args -p enable_depth:=false -p enable_infra1:=false -p enable_infra2:=false -p enable_gyro:=false -p enable_accel:=false
```

Then publish a prompt from the host:

```bash
source /opt/ros/humble/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
ros2 topic pub -1 /input_query std_msgs/msg/String "data: a person, a monitor, a chair"
```

Important model note:

- the model now answers according to the custom fine-tuned checkpoint, not the stock OWL-ViT behavior
- prompt quality depends on what labels or concepts the model was fine-tuned on

## 14. Why Building On A Stronger Non-Jetson Machine Is Not The Preferred Path

TensorRT engines are not generally portable across platforms, and JetPack does not support the TensorRT hardware-compatibility mode used for broader engine portability.

Practical consequence:

- a non-Jetson x86 workstation is not the safe place to build the final deployment engine for this Jetson
- the preferred path is to build on the target Jetson or a closely matching Jetson with the same JetPack and TensorRT stack

## 15. Troubleshooting

### `run_dev.sh` fails immediately

- Cause: the workspace root is not a Git repo.
- Fix: use the direct `docker run` command from section 1.

### `torchvision` imports but ops are missing

- Cause: incompatible prebuilt wheel.
- Fix: rebuild from source and copy the built package tree into `/home/admin/.local/lib/python3.10/site-packages`.

### Local model path fails in `OwlPredictor`

- Cause: `image_size` and `patch_size` were originally hardcoded by model name string.
- Fix: keep the local-directory `config.json` patch in `owl_predictor.py`.

### Engine build fails with GPU OOM

- Cause: TensorRT tactic search exceeds what the Jetson can allocate in its current memory state.
- Fix:
  - reboot first
  - do not launch camera or RViz before the build
  - use the exact successful command from section 10
  - keep the timing cache file for future rebuilds

### GPU direct inference without TensorRT fails

- Cause: the Jetson can still hit allocator failures when trying to run the full direct GPU model path without the engine.
- Fix: use the custom TensorRT engine path for deployment.

### ROS node starts but the engine file is missing

- Current behavior: the node warns and falls back to direct model inference.
- Recommended fix: rebuild or restore `my_model_image_encoder.engine`.

### `class_id` values in `/output_detections` are numbers

- They are indexes into the query list in order.
- Example:
  - `0` means the first phrase in the query string.
  - `1` means the second phrase.
  - `2` means the third phrase.

## 16. Save The Working Container State

After the setup worked, the container could be committed again if desired:

```bash
docker commit isaac_ros_dev-aarch64-container isaac_ros_dev-aarch64:nanoowl-ready
```

Do this only if you want the current Python environment and rebuilt packages preserved in the image itself.

## 17. Git Note

The custom model and engine binaries are large:

- `my_model/model.safetensors` is about `585 MiB`
- `my_model_image_encoder.engine` is about `174 MiB`

Do not commit these binaries to a normal GitHub repository unless you intentionally use Git LFS. The normal path is:

- keep the model folder locally on the edge device
- rebuild the engine locally when needed
