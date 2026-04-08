# NanoOWL on ADAONE

This workspace documents and implements a Jetson Orin Nano deployment of ROS 2 NanoOWL for the ADAONE small autonomous vehicle platform.

The project started as a straight ROS2-NanoOWL bring-up and grew into a systems study of what it takes to run open-vocabulary object detection on constrained hardware while the rest of a robot stack is still alive.

## What This Project Covers

- bringing up `ROS2-NanoOWL` inside an Isaac ROS style container on Jetson Orin Nano
- building TensorRT image-encoder engines locally on the Jetson
- swapping from the stock `google/owlvit-base-patch32` model to fine-tuned OWL-ViT checkpoints
- evaluating baseline and fine-tuned models on COCO 2017
- integrating NanoOWL into ADAONE as an alternative to the original YOLO perception path
- profiling how much CPU, RAM, GPU, and system headroom remain when perception and vehicle packages run together

## Why This Work Matters

Open-vocabulary detection is attractive for robotics because the operator can search for objects by text prompt instead of being limited to a fixed closed-set detector. The practical problem is that embedded robots do not run perception in isolation. They also need camera drivers, localization, control, and communication at the same time.

On this Jetson, the central question was not only "can NanoOWL run?" but also:

- can it stay on the GPU instead of falling back to CPU?
- can it coexist with the ADAONE control and localization stack?
- can it publish outputs in a form the rest of the vehicle software can actually use?

That is the real systems contribution of this workspace.

## Main Accomplishments

### 1. ROS2-NanoOWL was brought up successfully on Jetson Orin Nano

- Isaac ROS style container runtime was made to work with the existing workspace at `/home/ada2/boyang_ws`
- `torchvision` had to be rebuilt inside the container for this Jetson/PyTorch combination
- `ros2_nanoowl` was rebuilt and validated with sample-image and live-camera tests

### 2. Fine-tuned local OWL-ViT checkpoints were supported

- NanoOWL was patched so `model_name` can be a local Hugging Face model directory
- `image_size` and `patch_size` are now read from the local `config.json`
- the processor is loaded in a way that stays compatible with the fine-tuned checkpoints used in this project

### 3. TensorRT engines were compiled locally on the Jetson

- stock baseline `owl_image_encoder_patch32.engine` was used successfully for live deployment and COCO evaluation
- a fine-tuned checkpoint initially only built as a slow weight-streaming engine
- a faster normal FP16 TensorRT engine was later produced successfully for the same fine-tuned checkpoint

### 4. COCO 2017 evaluation was added and saved

The repository now includes a repeatable COCO evaluator:

- [eval_coco.py](src/nanoowl/examples/eval_coco.py)

Saved full-run comparison files:

- [coco_summary_baseline_full_cuda_trt.json](eval/coco/coco_summary_baseline_full_cuda_trt.json)
- [coco_results_baseline_full_cuda_trt.json](eval/coco/coco_results_baseline_full_cuda_trt.json)
- [coco_summary_owlvit_deal_imagenet_step55_full_cuda_trt_fp16.json](eval/coco/coco_summary_owlvit_deal_imagenet_step55_full_cuda_trt_fp16.json)
- [coco_results_owlvit_deal_imagenet_step55_full_cuda_trt_fp16.json](eval/coco/coco_results_owlvit_deal_imagenet_step55_full_cuda_trt_fp16.json)

### 5. NanoOWL was integrated as a YOLO-compatible choice for ADAONE

The ROS node was extended so NanoOWL can optionally publish the legacy ADAONE perception topics:

- `/yolo/detections`
- `/yolo/inference_image`

That means the existing downstream nodes can consume NanoOWL output with minimal changes, especially:

- `object_position_node`
- stop-sign and cone behavior nodes
- the control-center arbitration path

### 6. Live GPU deployment with the ADAONE stack was demonstrated

NanoOWL remained on GPU while running with:

- RealSense camera
- F1TENTH low-level stack
- control center
- object-position estimation
- and, in a heavier profile, LiDAR plus LiDAR localization

The successful recipe was:

- `device:=cuda`
- TensorRT image encoder enabled
- reduced camera profile such as `640x480@15`
- `publish_output_image:=false` when throughput matters

## Current Best COCO Comparison

Full COCO 2017 `val2017`, TensorRT on CUDA, threshold `0.1`, prompt template `a photo of {label}`:

| Metric | Baseline OWL-ViT | Fine-tuned OWL-ViT |
| --- | ---: | ---: |
| AP | 0.2486 | 0.2527 |
| AP50 | 0.3928 | 0.3972 |
| AP75 | 0.2635 | 0.2687 |
| AP small | 0.0902 | 0.0892 |
| AP medium | 0.2548 | 0.2592 |
| AP large | 0.4295 | 0.4409 |
| AR@100 | 0.3580 | 0.3525 |
| Seconds / image | 0.0954 | 0.1640 |
| Images / second | 10.48 | 6.10 |

Interpretation:

- the fine-tuned model is modestly better on the main precision metrics
- the largest gain is on medium and large objects
- the baseline remains faster on this Jetson
- the fine-tuned model became usable only after building a proper FP16 engine instead of staying on the earlier slow weight-streaming engine

For a deeper written analysis, see:

- [analysis_and_comparison_2026-04-08.md](eval/coco/analysis_and_comparison_2026-04-08.md)

## Live System Findings

Two live deployment regimes were tested.

### Reduced Perception-Focused Configuration

Components:

- RealSense camera at reduced resolution and frame rate
- NanoOWL on GPU
- depth-based `object_position_node`
- optional control stack, but no full localization burden

This mode gave the most comfortable headroom and proved that NanoOWL can function as the live perception module on the Jetson when the stack is kept lean.

### Heavier ADAONE Configuration

Components:

- RealSense camera
- NanoOWL on GPU
- `object_position_node`
- F1TENTH low-level stack
- `control_center_node`
- LiDAR
- LiDAR transformer
- LiDAR localization

Key observation:

- NanoOWL still remained on GPU and continued publishing detections
- the major extra CPU cost was actually `lidar_transformer_node`, not NanoOWL itself
- the system was near its practical limit, but it remained functional

## How NanoOWL Fits Into ADAONE

The image topic itself is mainly for visualization. The more important integration path is through detections.

Relevant flow:

1. camera publishes RGB and aligned depth
2. NanoOWL subscribes to the RGB stream
3. NanoOWL publishes:
   - structured detections on `/output_detections`
   - optional annotated image on `/output_image`
   - optional legacy outputs on `/yolo/detections` and `/yolo/inference_image`
4. `object_position_node` uses detections plus aligned depth to estimate object-relative position
5. control and behavior nodes can consume those downstream outputs

This means NanoOWL can contribute to the vehicle stack even without rewriting the entire perception layer first.

## Key Technical Lessons

- Jetson deployment is extremely sensitive to memory state during TensorRT engine builds.
- A model can be valid and still fail to build if the system is fragmented or under pressure.
- A prebuilt engine loading successfully is not the same thing as a fresh engine build succeeding.
- Weight-streaming engines can rescue a build that otherwise fails, but they may be much slower.
- The best embedded metric is not just detector FPS. It is whether the detector leaves enough room for the rest of the robot.
- Low GPU utilization does not mean the system is underused. CPU-side conversion, ROS transport, and memory movement can still dominate.
- For this stack, disabling annotated image publishing is one of the easiest throughput wins.

## Important Documents In This Workspace

- [instructions.md](instructions.md)
  Full bring-up notes, patch history, engine-build history, and failure-mode documentation.
- [manual.md](manual.md)
  Day-to-day runbook and launch commands.
- [NANOOWL_MODEL_SWAP_HANDOFF.md](NANOOWL_MODEL_SWAP_HANDOFF.md)
  Model-swap-specific handoff notes.
- [analysis_and_comparison_2026-04-08.md](eval/coco/analysis_and_comparison_2026-04-08.md)
  Consolidated evaluation and runtime comparison report.

## Repository Layout

Top-level items most relevant to this project:

- `src/ROS2-NanoOWL`
  ROS 2 package and launch files for NanoOWL.
- `src/nanoowl`
  core NanoOWL Python implementation and COCO evaluator.
- `src/torch2trt`
  TensorRT support dependency used during engine generation.
- `eval/coco`
  saved benchmark outputs and the written comparison report.
- `models`
  local fine-tuned model directories used during experiments.

## Large Artifacts Not Stored In Git

The GitHub mirror intentionally excludes heavy local artifacts such as:

- `.engine` TensorRT engine files
- `.onnx` exports
- timing cache files
- build/install/log folders
- private or large model weights that were not intended for version control

That keeps the repository lightweight while still preserving the code, commands, and measured results needed to reproduce the work.

## Recommended Next Steps

- benchmark more domain-relevant datasets beyond COCO
- quantify memory headroom and coexistence with more vehicle subsystems
- decide whether the project should prioritize speed, accuracy, or deployability
- replace more of the legacy string-based perception interface with structured messages
- investigate whether a camera-only localization path is worth adding for a lighter all-vision stack

## Bottom Line

This project shows that open-vocabulary perception on a Jetson-class robot is possible, but only when model deployment, TensorRT engine strategy, ROS integration, and whole-system resource pressure are treated as one systems problem instead of separate steps.
