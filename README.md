# NanoOWL on ADAONE

This workspace documents a full embedded deployment effort for open-vocabulary object detection on a Jetson Orin Nano using ROS 2 NanoOWL, TensorRT, and the ADAONE small autonomous vehicle software stack.

The project is no longer just a "can we launch NanoOWL?" exercise. It has become a systems study of how to make open-vocabulary perception coexist with a real robot stack on limited hardware.

## Executive Summary

This project answers four practical questions:

1. Can ROS2-NanoOWL be deployed on a Jetson Orin Nano with TensorRT?
2. Can a fine-tuned OWL-ViT checkpoint be integrated cleanly instead of only using the stock NanoOWL model?
3. Can NanoOWL act as a drop-in perception choice for ADAONE, alongside or instead of the original YOLO path?
4. Can NanoOWL stay on GPU while the rest of the vehicle software is alive, instead of falling back to CPU?

Current answer:

- yes, ROS2-NanoOWL runs on this Jetson
- yes, fine-tuned Hugging Face checkpoints are supported
- yes, NanoOWL can publish ADAONE-compatible outputs
- yes, NanoOWL can remain on GPU in a practical deployment configuration
- yes, a corrected fine-tuned TensorRT engine now runs near baseline speed instead of the earlier unacceptable slowdown

The most important takeaway is that the main challenge is not model loading by itself. The real challenge is resource-aware deployment inside a larger robotics system.

## Why This Project Exists

Open-vocabulary detection matters because robots often need to reason about text-specified objects rather than a fixed closed-set label list. A perception system that can respond to prompts like `a chair`, `a monitor`, or `a stop sign` is more flexible than a detector trained only for a small fixed class set.

But embedded robots do not run perception in isolation. They also need:

- camera drivers
- localization
- control
- message transport
- visualization
- often other perception nodes at the same time

That means the real problem is not:

> Can OWL-ViT run once on a Jetson?

The real problem is:

> Can open-vocabulary perception run fast enough, stay on GPU, leave enough headroom for the rest of the robot, and integrate into the existing ROS pipeline?

This repository exists to answer that systems question with code, measurements, and deployment artifacts.

## Project Goals

The project currently has five concrete goals:

- bring up ROS2-NanoOWL in a repeatable Jetson-friendly environment
- support both the stock OWL-ViT checkpoint and fine-tuned local checkpoints
- compile TensorRT image-encoder engines locally on the Jetson
- measure benchmark accuracy and runtime on COCO 2017
- connect NanoOWL to ADAONE in a way that the rest of the vehicle stack can use

## Latest ADAONE Status

The latest integrated state is stronger than the earlier "NanoOWL on Jetson" milestone.

The project now has evidence for all of these:

- the proper low-level wheel-driver path on this machine is the explicit `ada_system` Docker workflow, not the stale shortcut path
- NanoOWL can publish ADAONE-compatible legacy detections on `/yolo/detections`
- ADAONE can run a camera-only scene-selection demo that chooses between `indoor` and `outdoor` query sets
- the scene-selection logic now ignores both:
  - exact query overlap between indoor and outdoor probe lists
  - scene-neutral human-family labels such as `person`, `people`, and `pedestrian`
- the low-level chassis stack and the perception stack can be tested independently, which made debugging much faster and safer

Two practical caveats matter:

- for the final indoor/outdoor validation, the robust path was a warmed-up baseline NanoOWL node on CPU inference, because the TensorRT/GPU path was still unstable under the already-loaded ADAONE stack
- the wheel-control path works only when the low-level F1TENTH driver is brought up through the correct Foxy install and the correct VESC serial device

## What Was Built

### 1. Jetson ROS2-NanoOWL deployment

ROS2-NanoOWL was brought up successfully in an Isaac ROS style container using the workspace mounted from:

- `/home/ada2/boyang_ws`

Important source trees:

- `src/ROS2-NanoOWL`
- `src/nanoowl`
- `src/torch2trt`
- `src/isaac_ros_common`

### 2. Fine-tuned model support

NanoOWL was patched so `model_name` can be a local Hugging Face directory instead of only official Google model strings.

That work includes:

- reading `image_size` and `patch_size` from local `config.json`
- loading the processor in a compatible way for the fine-tuned checkpoints used here
- keeping the Jetson-friendly CPU/GPU split that makes TensorRT deployment stable

### 3. TensorRT engine generation on the Jetson

This project tested several engine-generation paths:

- stock baseline engine
- slower rescue-style fine-tuned engine
- corrected stock-style fine-tuned engine

The final corrected fine-tuned engine is:

- `src/nanoowl/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`
- mirrored to `src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`

### 4. COCO evaluation pipeline

A repeatable evaluation script was added here:

- [eval_coco.py](src/nanoowl/examples/eval_coco.py)

This made it possible to compare:

- baseline model accuracy and speed
- fine-tuned model accuracy and speed
- bad engine builds vs corrected engine builds

### 5. ADAONE integration path

NanoOWL was extended so it can publish:

- structured detections on `/output_detections`
- annotated frames on `/output_image`
- optional ADAONE-compatible legacy topics:
  - `/yolo/detections`
  - `/yolo/inference_image`

That allows the existing downstream ADAONE stack to consume NanoOWL detections without a full perception rewrite.

## System Context

There are really three interacting layers in this project:

### NanoOWL layer

- OWL-ViT model loading
- text prompt encoding
- image encoding through TensorRT
- open-vocabulary detection decoding

### ROS integration layer

- `ros2_nanoowl` node
- launch files
- camera input subscription
- legacy detection-topic compatibility for ADAONE

### ADAONE vehicle layer

- RealSense camera
- depth-based object position estimation
- F1TENTH low-level stack
- control center
- optional LiDAR and LiDAR localization

This project focuses on the boundary between these layers, because that is where most of the practical deployment friction shows up.

## Current Default Deployment

The current default ROS configuration points to the fine-tuned model and the corrected fast engine.

Default model:

- `/workspaces/isaac_ros-dev/models/owlvit_deal_imagenet_step55_hf`

Default engine:

- `/workspaces/isaac_ros-dev/src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`

Source files that currently define those defaults:

- [nano_owl_py.py](src/ROS2-NanoOWL/ros2_nanoowl/nano_owl_py.py)
- [nano_owl_example.launch.py](src/ROS2-NanoOWL/launch/nano_owl_example.launch.py)
- [camera_input_example.launch.py](src/ROS2-NanoOWL/launch/camera_input_example.launch.py)

Recommended live settings on this Jetson:

- `device:=cuda`
- TensorRT engine enabled
- `publish_output_image:=false` when throughput matters
- reduced camera profile such as `640x480@15`

Important operational nuance:

- the fine-tuned TensorRT path is still the recommended default for benchmarked and deployment-oriented NanoOWL use
- the scene-classification demo may still need a lighter fallback path if the full ADAONE stack is already consuming too much GPU memory

## Evaluation Summary

### COCO 2017 Full Benchmark

All main comparisons use:

- dataset: COCO 2017 `val2017`
- images: `5000`
- threshold: `0.1`
- prompt template: `a photo of {label}`
- backend: TensorRT on CUDA

### Baseline vs Corrected Fine-Tuned Engine

| Metric | Baseline OWL-ViT | Fine-tuned OWL-ViT | Delta |
| --- | ---: | ---: | ---: |
| AP | 0.2486 | 0.2517 | +0.0031 |
| AP50 | 0.3928 | 0.3955 | +0.0027 |
| AP75 | 0.2635 | 0.2676 | +0.0041 |
| AP small | 0.0902 | 0.0894 | -0.0008 |
| AP medium | 0.2548 | 0.2590 | +0.0042 |
| AP large | 0.4295 | 0.4380 | +0.0086 |
| AR@1 | 0.2482 | 0.2476 | -0.0006 |
| AR@10 | 0.3515 | 0.3458 | -0.0057 |
| AR@100 | 0.3580 | 0.3510 | -0.0070 |
| Seconds / image | 0.0954 | 0.1050 | +0.0096 |
| Images / second | 10.48 | 9.52 | -0.96 |

Interpretation:

- the fine-tuned model is still modestly better on precision
- the largest gain remains on larger objects
- small-object precision is slightly worse than baseline
- recall is slightly lower than baseline
- the speed penalty is now small enough to be practical on the Jetson

Saved benchmark files:

- [coco_summary_baseline_full_cuda_trt.json](eval/coco/coco_summary_baseline_full_cuda_trt.json)
- [coco_results_baseline_full_cuda_trt.json](eval/coco/coco_results_baseline_full_cuda_trt.json)
- [coco_summary_owlvit_deal_imagenet_step55_full_cuda_trt_stock_opset17.json](eval/coco/coco_summary_owlvit_deal_imagenet_step55_full_cuda_trt_stock_opset17.json)
- [coco_results_owlvit_deal_imagenet_step55_full_cuda_trt_stock_opset17.json](eval/coco/coco_results_owlvit_deal_imagenet_step55_full_cuda_trt_stock_opset17.json)

### Why The Earlier Fine-Tuned Engine Looked So Bad

The earlier fine-tuned engine was not a fair representation of the checkpoint.

That engine path produced:

- similar accuracy
- much worse runtime

The corrected engine showed that the slowdown was caused by a poor TensorRT build artifact rather than by the fine-tuned checkpoint itself.

Direct `trtexec` checks on this Jetson showed:

- baseline engine:
  - about `11.21 qps`
  - mean GPU compute `89.16 ms`
- earlier bad fine-tuned engine:
  - about `3.70 qps`
  - mean GPU compute `270.35 ms`
- corrected stock-style fine-tuned engine:
  - about `26.62 qps`
  - mean GPU compute `37.56 ms`

This was one of the most important lessons in the project: engine build path matters as much as checkpoint choice.

### Detailed Comparison Reports

- [analysis_and_comparison_2026-04-08.md](eval/coco/analysis_and_comparison_2026-04-08.md)
  live runtime profiling and earlier model comparison
- [analysis_and_comparison_2026-04-09.md](eval/coco/analysis_and_comparison_2026-04-09.md)
  corrected fine-tuned engine comparison against baseline

## Live Deployment Findings

Two live deployment regimes were tested on the Jetson.

### Reduced Perception-Focused Configuration

Components:

- RealSense camera
- NanoOWL on GPU
- depth-based object-position estimation
- optionally the control stack, but without the heaviest localization burden

This mode showed that NanoOWL can be a practical live perception service on this hardware if the system is configured carefully.

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

Important result:

- NanoOWL stayed on GPU
- detections kept publishing
- the system remained near its practical limit but did not collapse

Important bottleneck:

- the largest extra CPU consumer in the heavier configuration was `lidar_transformer_node`, not NanoOWL itself

### Scene-Aware Camera-Only Demo

The project now includes a camera-only reactive demo path intended for testing and presentation rather than full autonomous navigation.

That path adds:

- `scene_aware_query_manager`
- `reactive_behavior_controller`
- ADAONE-compatible NanoOWL legacy outputs

What the scene manager does:

1. publish an indoor probe query
2. publish an outdoor probe query
3. accumulate confidence only for labels that are unique to each scene
4. ignore scene-neutral human-family labels
5. lock the system to `indoor` or `outdoor`
6. publish the final scene-specific query set

Latest confirmed result on this machine:

- the scene manager locked to `indoor`
- the scored decision was based on real detections instead of just a fallback default
- indoor detections included labels like `bottle`, `chair`, and `box`

## How NanoOWL Contributes To ADAONE

The most important integration output is not the annotated image. It is the detection stream.

Practical data flow:

1. camera publishes RGB and aligned depth
2. NanoOWL subscribes to the RGB image
3. NanoOWL publishes:
   - `/output_detections`
   - `/output_image`
   - optionally `/yolo/detections`
   - optionally `/yolo/inference_image`
4. `object_position_node` combines detections with aligned depth
5. downstream ADAONE behavior or control logic can use those results

That means NanoOWL can contribute meaningfully to the vehicle stack even before the entire legacy perception interface is redesigned.

## What This Project Proves

At this point, the project supports several claims with real evidence:

- ROS2-NanoOWL can be deployed on Jetson Orin Nano
- fine-tuned OWL-ViT checkpoints can be integrated into that deployment
- TensorRT engine generation for the fine-tuned checkpoint is feasible on-device
- NanoOWL can serve as an ADAONE-compatible perception option
- open-vocabulary perception can remain on GPU while a meaningful portion of the robot stack is active
- a badly built engine can make a good model look unusable
- a corrected engine can recover near-baseline speed while retaining the fine-tuned model's accuracy advantage

## What This Project Does Not Yet Prove

There are still important boundaries:

- this repository does not currently contain a camera-only vehicle localization stack
- full long-duration closed-loop driving validation with NanoOWL in the live loop is not yet the main demonstrated result
- the current ADAONE compatibility path still includes legacy string-based interfaces that should eventually be replaced with stronger message types
- benchmark results are strong for COCO comparison, but more task-specific datasets are still needed for a domain-specific claim

## Problems We Hit And How We Solved Them

Several of the most important project lessons came from failures rather than first-pass success.

### 1. The bad fine-tuned TensorRT engine made the model look unusable

Problem:

- the first fine-tuned engine was dramatically slower than baseline

What we learned:

- the checkpoint was not the main problem
- the engine artifact and builder path were the real problem

What fixed it:

- rebuilding through the corrected stock-style TensorRT path
- validating with both COCO and direct `trtexec` measurements

### 2. The low-level wheel driver was not being launched from the right environment

Problem:

- earlier chassis tests used a partial path that translated commands but did not fully match the intended `ada_system` workflow

What we learned:

- `install/setup.bash` was stale for the Foxy low-level stack on this machine
- the working low-level environment was `install_foxy/setup.bash`

What fixed it:

- launching through `ada_system/run_container.sh`
- sourcing `install_foxy/setup.bash`
- running `ros2 launch f1tenth_stack bringup_launch.py` inside that container

### 3. The wrong VESC serial path hid the real wheel-driver behavior

Problem:

- the controller path moved during testing between `/dev/ttyUSB0` and `/dev/ttyACM0`

What we learned:

- the correct path for the successful wheel-spin test was `/dev/ttyACM0`

What fixed it:

- using the explicit VESC config override
- verifying live `/sensors/core` feedback instead of trusting command translation alone

### 4. Direct `/ackermann_cmd` testing was misleading while `control_center` was active

Problem:

- host-side control nodes were still publishing zero-speed commands, which could cancel direct drive tests

What we learned:

- when `control_center_node` is active, upstream testing should go through `/purepursuit_cmd`

What fixed it:

- using `/purepursuit_cmd` for controlled drive-path testing
- isolating stop-sign behavior and other overrides during debugging

### 5. Scene classification initially "worked" only by default fallback

Problem:

- the first indoor/outdoor run locked to `indoor`, but only because both scores were zero

What we learned:

- NanoOWL warm-up timing matters
- shared or human-like labels should not decide the scene

What fixed it:

- rerunning the scene manager after NanoOWL was already warm
- adding overlap filtering
- adding `scene_neutral_labels` for human-family classes

## Key Technical Lessons

- Jetson TensorRT engine builds are very sensitive to memory state and builder path.
- A model checkpoint can be fine while the engine artifact is bad.
- A prebuilt engine loading successfully is not the same thing as being easy to rebuild.
- Weight-streaming or rescue-style engines can recover deployability but may destroy throughput.
- The right metric is not detector FPS alone. It is detector usefulness inside a whole robot stack.
- GPU utilization by itself is not enough to interpret system health.
- CPU-side conversions, ROS transport, and auxiliary nodes can be the real bottleneck.
- Disabling annotated output image publishing is one of the easiest throughput wins.

## Research Framing And Possible Paper Story

The strongest paper angle is not:

> We ran OWL-ViT on a Jetson.

The stronger framing is:

> Open-vocabulary perception on embedded robots is limited by system coexistence, memory headroom, and deployment strategy, not just by nominal model accuracy.

A clean story for this repository is:

- open-vocabulary detection is attractive for robotics
- embedded platforms make deployment difficult
- a naïve engine build can make a good model appear unusable
- a corrected deployment path can recover near-baseline runtime
- the real value is making perception coexist with the rest of the robot

## Suggested Next Work And Rough Effort Estimates

These are practical next steps if the project continues.

### 1. Keep The Docs Aligned With The Live Deployment

Goal:

- keep every runbook aligned with:
  - the corrected `..._stock_opset17.engine`
  - the proper `ada_system` low-level driver path
  - the scene-aware indoor/outdoor workflow

Estimated effort:

- `0.5` day

Risk:

- low

### 2. Repeat Live ADAONE Profiling With The Corrected Engine

Goal:

- verify whether the corrected fast engine improves the live integrated stack, not just COCO evaluation

Estimated effort:

- `0.5` to `1` day

Risk:

- low to medium

### 3. Run Domain-Specific Evaluation Beyond COCO

Goal:

- measure whether the fine-tuned checkpoint is actually better on the objects ADAONE cares about

Estimated effort:

- `2` to `4` days

Risk:

- medium

### 4. Replace More Of The Legacy Detection Interface

Goal:

- reduce dependence on string-formatted detection messages

Estimated effort:

- `1` to `2` days

Risk:

- medium

### 5. Produce Paper-Quality Figures And Ablations

Goal:

- convert the engineering results into publishable tables, plots, and claims

Estimated effort:

- `3` to `5` days

Risk:

- medium

### 6. Explore Camera-Only Vehicle Localization

Goal:

- determine whether ADAONE can shed LiDAR in some configurations

Estimated effort:

- multi-week research task

Risk:

- high

This is a separate research problem, not a small extension of the current work.

## Recommended Reading Order In This Repository

If you are new to the project, read these in order:

1. [README.md](README.md)
2. [ADAONE_SYSTEM_CHANGES.md](ADAONE_SYSTEM_CHANGES.md)
3. [instructions.md](instructions.md)
4. [manual.md](manual.md)
5. [analysis_and_comparison_2026-04-09.md](eval/coco/analysis_and_comparison_2026-04-09.md)
6. [NANOOWL_MODEL_SWAP_HANDOFF.md](NANOOWL_MODEL_SWAP_HANDOFF.md)

## Repository Layout

Main folders:

- `src/ROS2-NanoOWL`
  ROS node, launch files, and integration code
- `src/nanoowl`
  core prediction code, engine export/build helpers, evaluator
- `src/torch2trt`
  TensorRT support dependency used during the engine workflow
- `eval/coco`
  benchmark results and comparison notes
- `models`
  local fine-tuned checkpoints used during experiments

## Large Artifacts Not Stored In Git

The GitHub mirror intentionally does not store everything generated locally.

Common excluded artifact types:

- TensorRT `.engine` files
- ONNX exports
- timing caches
- build/install/log directories
- large or private model weights that do not belong in source control

The repository is meant to preserve:

- source changes
- launch logic
- evaluation JSONs
- written analysis
- reproducible commands and lessons learned

## Bottom Line

This project shows that open-vocabulary perception on a Jetson-class robot is feasible, but only when model choice, TensorRT engine generation, ROS integration, and overall system resource pressure are treated as one connected engineering problem.

The fine-tuned model is now supported, benchmarked, and deployable with a corrected engine that keeps its accuracy advantage while staying close to baseline runtime.
