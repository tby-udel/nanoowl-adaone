# ADAONE System Changes

This file records the code and system-level changes made while integrating NanoOWL with ADAONE on this Jetson Orin Nano, plus the vehicle-side bring-up changes needed to reproduce the working setup on other ADAONE cars.

It is meant to answer two questions:

1. What exactly was changed?
2. What must be reproduced on another ADAONE for the same behavior to work?

## 1. Scope

The work touched four main areas:

- `ROS2-NanoOWL` in `/home/ada2/boyang_ws/src/ROS2-NanoOWL`
- `nanoowl` in `/home/ada2/boyang_ws/src/nanoowl`
- `CARKit` in `/home/ada2/CARKit`
- low-level F1TENTH container bring-up in `/home/ada2/ada_system` and `/home/ada2/NavOS`

## 2. High-Level Goal

The system was extended from a standalone NanoOWL demo into an ADAONE-compatible perception module that can:

- run OWL-ViT / fine-tuned OWL-ViT on the Jetson
- publish detections on NanoOWL-native topics
- also publish ADAONE-compatible legacy topics such as `/yolo/detections`
- participate in a camera-only reactive demo
- classify the environment as `indoor` or `outdoor`
- use scene-specific query sets after the mode is chosen
- coexist with the ADAONE control and F1TENTH chassis stack

## 3. Files Changed And Why

### 3.1 ROS2-NanoOWL Runtime Integration

File: `src/ROS2-NanoOWL/ros2_nanoowl/nano_owl_py.py`

Changes:

- added parameters for:
  - `model`
  - `device`
  - `image_encoder_engine`
  - `publish_output_image`
  - `publish_legacy_outputs`
  - `legacy_detection_topic`
  - `legacy_image_topic`
- added legacy ADAONE-compatible output publishing:
  - `/yolo/detections`
  - `/yolo/inference_image`
- added query caching so text embeddings are only recomputed when the query changes
- made TensorRT engine usage conditional on:
  - device being `cuda`
  - engine path existing
- preserved fallback behavior when TensorRT engine is not available

Reason:

- ADAONE’s existing downstream perception utilities do not consume NanoOWL `vision_msgs` directly.
- They expect YOLO-style string detections and optionally an annotated image.
- This file is the compatibility bridge between NanoOWL and the existing ADAONE perception pipeline.

### 3.2 Custom Model / TensorRT / Predictor Behavior

File: `src/nanoowl/nanoowl/owl_predictor.py`

Changes:

- added support for local Hugging Face model directories by reading `config.json`
- used local model metadata to infer:
  - `image_size`
  - `patch_size`
- added more deployment-safe model loading behavior for this Jetson stack
- supported both:
  - direct PyTorch image encoder path
  - TensorRT image encoder path
- enabled the custom fine-tuned checkpoint to be used with ROS2-NanoOWL and COCO evaluation

Reason:

- the project moved beyond the stock `google/owlvit-base-patch32` checkpoint
- the ROS node needed to support a locally fine-tuned OWL-ViT checkpoint
- TensorRT compilation and runtime on Jetson needed a more robust path than the original upstream assumptions

### 3.3 ROS2-NanoOWL Launch Defaults

Files:

- `src/ROS2-NanoOWL/launch/nano_owl_example.launch.py`
- `src/ROS2-NanoOWL/launch/camera_input_example.launch.py`
- `src/ROS2-NanoOWL/launch/ada_reactive_perception.launch.py`

Changes:

- updated launch defaults to point to the current recommended model and engine
- added an ADAONE-focused launch file for reactive perception usage
- ensured the ADAONE-facing launch path can publish legacy outputs for compatibility

Reason:

- the raw upstream demo launches were not enough for the ADAONE perception stack
- a container-side launch dedicated to ADAONE integration was needed

### 3.4 CARKit Object Parsing Fix

File: `/home/ada2/CARKit/src/ada/ada/object_position.py`

Change:

- fixed detection-string parsing so multi-word labels such as `stop sign` are handled correctly

Reason:

- open-vocabulary labels are not restricted to single words
- the previous parser behavior was too brittle for NanoOWL outputs and scene-aware prompts

### 3.5 Scene-Aware Query Selection

File: `/home/ada2/CARKit/src/ada/ada/scene_aware_query_manager.py`

Added:

- startup indoor/outdoor probing
- indoor probe query list
- outdoor probe query list
- scene locking to `indoor` or `outdoor`
- final scene-specific query publishing after lock

Later updates:

- added richer outdoor vocabulary:
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
- kept human-related indoor labels:
  - `person`
  - `people`
- added `scene_neutral_labels` so semantically shared human-family labels do not affect indoor/outdoor scoring:
  - `person`
  - `people`
  - `pedestrian`
  - `pedestrians`
  - `human`
  - `humans`
- added overlap filtering so if a label accidentally appears in both indoor and outdoor probe lists later, it is removed from the scene vote
- added runtime logging for ignored shared/neutral labels

Reason:

- the scene vote should be based on genuinely scene-specific evidence
- humans may appear in both indoor and outdoor environments, so they should remain detectable but should not decide the scene mode

### 3.6 Camera-Only Reactive Behavior

Files:

- `/home/ada2/CARKit/src/ada/ada/reactive_behavior_controller.py`
- `/home/ada2/CARKit/src/ada/launch/nanoowl_camera_reactive_demo.launch.py`

Changes:

- added a behavior controller that converts perception results into reactive Ackermann commands
- added behavior categories:
  - stop
  - slow
  - bypass
- added scene-aware launch defaults for:
  - indoor queries
  - outdoor queries
  - motion enable/disable
  - stop/slow/bypass label lists

Reason:

- the intended camera-only demo is reactive semantic behavior, not full map-based autonomy
- this provides a vision-only path that can be demonstrated without LiDAR localization

### 3.7 ADA Package Registration

Files:

- `/home/ada2/CARKit/src/ada/setup.py`
- `/home/ada2/CARKit/src/ada/package.xml`

Changes:

- registered the new ADA Python executables and runtime dependencies needed for the new perception-demo nodes

Reason:

- without these changes, the new nodes cannot be launched via ROS2 package discovery

### 3.8 F1TENTH Container Entry Point

Files:

- `/home/ada2/CARKit/src/ada/launch/f1tenth_entrypoint.sh`
- `/home/ada2/NavOS/src/ada/launch/f1tenth_entrypoint.sh`

Changes:

- updated the entrypoint to source the working Foxy install tree
- used `install_foxy/setup.bash` instead of the stale `install/setup.bash` path
- passed the explicit VESC config override during bring-up

Reason:

- the README-style container workflow was stale on this machine
- the working Foxy package set lives under `install_foxy`
- the low-level chassis stack needed an explicit known-good VESC config path

### 3.9 VESC Config Override

Files:

- `/home/ada2/ada_system/vesc_usb0_test.yaml`
- `/home/ada2/boyang_ws/runtime/vesc_usb0_test.yaml`

Changes:

- added explicit VESC parameter files used during bring-up debugging
- updated the serial port to the controller path that actually worked during the successful wheel-spin test:
  - `/dev/ttyACM0`

Reason:

- the chassis stack initially used the wrong serial path at various points
- once `/dev/ttyACM0` was used and the proper Docker bring-up path was followed, the controller reported live state and the wheels responded

## 4. Important Runtime Findings

### 4.1 Proper Wheel Driver Path

The correct low-level wheel driver path was the explicit `ada_system` Docker workflow:

```bash
cd /home/ada2/ada_system
./run_container.sh
```

Inside that container:

```bash
source install_foxy/setup.bash
ros2 launch f1tenth_stack bringup_launch.py
```

This mattered because:

- `install/setup.bash` was incomplete/stale for the low-level chassis stack
- `install_foxy/setup.bash` contained the working `f1tenth_stack`, `vesc_driver`, and `vesc_ackermann` packages

### 4.2 Scene Selection Test Result

The scene-aware logic was validated using live camera input with warmed-up NanoOWL.

Observed result:

- indoor probe produced indoor-object hits
- outdoor probe produced zero outdoor hits
- scene mode locked to `indoor`

Important nuance:

- the first test failed because the scene probe started before NanoOWL had warmed up enough to emit detections
- rerunning the scene manager against an already-running NanoOWL node produced the correct detection-driven `indoor` decision
- a later logic hardening step excluded both shared labels and scene-neutral human-family labels from scene scoring

### 4.3 Drive-Command Path Finding

The low-level driver was not enough by itself to make wheel-control tests easy to interpret.

Important findings:

- when `control_center_node` is active, direct `/ackermann_cmd` testing can be misleading
- host-side zero-speed publishers can override or compete with direct command injection
- upstream testing should go through `/purepursuit_cmd` when the full ADAONE control path is active

Reason:

- that path matches the active host-side arbitration logic more closely
- it made it possible to verify the whole command chain cleanly:
  - `/purepursuit_cmd`
  - `/ackermann_cmd`
  - `/commands/motor/speed`
  - `/sensors/core`

### 4.4 GPU / TensorRT Stability

Under heavier full-stack conditions, the TensorRT/GPU path was not consistently stable for the indoor/outdoor classification test.

For the successful scene-selection validation, the baseline model on CPU inference was used as a robustness fallback.

This means:

- the scene-selection logic itself is validated
- the final production GPU deployment path for this exact scene-selection workflow still needs more hardening under full system load

## 5. Reproduction Checklist For Another ADAONE

On another ADAONE, reproduce these categories in this order:

### 5.1 Workspaces And Images

- `sensor_ws`
- `CARKit`
- `ada_system`
- `boyang_ws`
- Docker image: `ariiees/ada:foxy-f1tenth`
- Docker image for NanoOWL / Isaac ROS

### 5.2 Low-Level Chassis

- verify the real VESC serial device
- update the explicit VESC config override if the device is not `/dev/ttyACM0`
- launch the chassis stack from the container using `install_foxy/setup.bash`

### 5.3 CARKit Build

Rebuild after copying the changed ADA files:

```bash
cd /home/ada2/CARKit
source /opt/ros/humble/setup.bash
source /home/ada2/sensor_ws/install/setup.bash
colcon build --symlink-install --packages-select ada
```

### 5.4 NanoOWL Build

Rebuild after copying the changed NanoOWL files:

```bash
docker exec -u admin isaac_ros_dev-aarch64-container bash -lc '
source /opt/ros/humble/setup.bash
cd /workspaces/isaac_ros-dev/src/nanoowl
python3 -m pip install --user --no-build-isolation .
cd /workspaces/isaac_ros-dev
colcon build --symlink-install --packages-select ros2_nanoowl
'
```

### 5.5 Scene-Aware Perception

Verify these topics exist and behave as expected:

- `/camera/camera/color/image_raw`
- `/input_query`
- `/scene_mode`
- `/yolo/detections`
- `/output_detections`

### 5.6 Final Sanity Checks

- confirm human-like labels are present in the final query sets
- confirm human-like labels do not affect scene scoring
- confirm shared labels between indoor and outdoor probes are ignored
- confirm the low-level chassis uses the correct serial device

## 6. Current Default Scene Vocab

### 6.1 Indoor Probe

- `person`
- `people`
- `chair`
- `desk`
- `monitor`
- `bottle`
- `laptop`

### 6.2 Outdoor Probe

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

### 6.3 Scene-Neutral Labels

These stay detectable, but do not influence the indoor/outdoor score:

- `person`
- `people`
- `pedestrian`
- `pedestrians`
- `human`
- `humans`

## 7. Files To Copy If Reproducing On Another ADAONE

At minimum, carry these forward:

- `/home/ada2/boyang_ws/src/ROS2-NanoOWL/ros2_nanoowl/nano_owl_py.py`
- `/home/ada2/boyang_ws/src/ROS2-NanoOWL/launch/ada_reactive_perception.launch.py`
- `/home/ada2/boyang_ws/src/nanoowl/nanoowl/owl_predictor.py`
- `/home/ada2/CARKit/src/ada/ada/object_position.py`
- `/home/ada2/CARKit/src/ada/ada/scene_aware_query_manager.py`
- `/home/ada2/CARKit/src/ada/ada/reactive_behavior_controller.py`
- `/home/ada2/CARKit/src/ada/launch/nanoowl_camera_reactive_demo.launch.py`
- `/home/ada2/CARKit/src/ada/setup.py`
- `/home/ada2/CARKit/src/ada/package.xml`
- `/home/ada2/CARKit/src/ada/launch/f1tenth_entrypoint.sh`
- `/home/ada2/NavOS/src/ada/launch/f1tenth_entrypoint.sh`
- `/home/ada2/ada_system/vesc_usb0_test.yaml`

## 8. Current Status

Working:

- low-level wheel control through the proper `ada_system` container workflow
- camera-based indoor/outdoor scene selection logic
- NanoOWL to ADAONE compatibility outputs
- camera-only reactive perception components

Still sensitive:

- TensorRT/GPU stability under a heavier full ADAONE runtime load
- machine-specific serial device naming for the VESC
- launch order and warm-up timing for the indoor/outdoor probe
