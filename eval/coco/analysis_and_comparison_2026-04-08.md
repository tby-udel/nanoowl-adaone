# NanoOWL Evaluation And Runtime Comparison

Generated: 2026-04-08 16:32:35 EDT

## Scope

This report summarizes two kinds of evaluation:

1. COCO 2017 `val2017` benchmark results saved in:
   - `/home/ada2/boyang_ws/eval/coco/coco_summary_baseline_full_cuda_trt.json`
   - `/home/ada2/boyang_ws/eval/coco/coco_summary_owlvit_deal_imagenet_step55_full_cuda_trt_fp16.json`
2. Live Jetson Orin runtime profiling while running NanoOWL on GPU inside the ADAONE stack.

The goal is to compare:

- baseline OWL-ViT (`google/owlvit-base-patch32`)
- fine-tuned OWL-ViT (`owlvit_deal_imagenet_step55_hf`) with the faster FP16 TensorRT engine

and to answer whether NanoOWL can remain on GPU while the required packages are running.

## COCO Benchmark Comparison

### Evaluation Setup

- Dataset: COCO 2017 `val2017`
- Images: 5000
- Prompt template: `a photo of {label}`
- Threshold: `0.1`
- Backend: TensorRT on `cuda`
- Padding: `pad_square=false`

### Summary Table

| Metric | Baseline OWL-ViT | Fine-tuned OWL-ViT | Delta (new - baseline) |
| --- | ---: | ---: | ---: |
| AP | 0.2486 | 0.2527 | +0.0041 |
| AP50 | 0.3928 | 0.3972 | +0.0044 |
| AP75 | 0.2635 | 0.2687 | +0.0052 |
| AP small | 0.0902 | 0.0892 | -0.0010 |
| AP medium | 0.2548 | 0.2592 | +0.0044 |
| AP large | 0.4295 | 0.4409 | +0.0114 |
| AR@100 | 0.3580 | 0.3525 | -0.0056 |
| Detections | 39475 | 36236 | -3239 |
| Seconds / image | 0.0954 | 0.1640 | +0.0686 |
| Images / second | 10.48 | 6.10 | -4.38 |

### Benchmark Interpretation

- The fine-tuned model is slightly better on the main precision metrics:
  - `AP +0.0041`
  - `AP50 +0.0044`
  - `AP75 +0.0052`
- The biggest gain is on large objects:
  - `AP_large +0.0114`
- The fine-tuned model is slightly worse on:
  - `AP_small -0.0010`
  - `AR@100 -0.0056`
- The faster FP16 engine recovered most of the speed lost in the earlier slow rescue build, but it is still slower than the baseline engine:
  - baseline throughput: `10.48 img/s`
  - fine-tuned throughput: `6.10 img/s`
  - speed ratio: the fine-tuned model is about `1.72x` slower

### Benchmark Conclusion

For offline benchmark accuracy, the fine-tuned model is modestly better than the baseline, especially on medium and large objects. For throughput-sensitive deployment, the baseline model still has the stronger speed profile on this Jetson.

## Live Runtime Profiling

## Configuration A: GPU NanoOWL + Camera + Object Position + Control Stack

### Active Components

- RealSense camera at `640x480@15`
- NanoOWL on GPU with TensorRT
- `object_position_node`
- F1TENTH low-level stack in `f1tenth_container`
- `control_center_node`

### Key Settings

- `device:=cuda`
- TensorRT engine: `owl_image_encoder_patch32.engine`
- `publish_output_image:=false`
- `publish_legacy_outputs:=true`

### Measured Runtime

- camera topic `/camera/camera/color/image_raw`: about `8.6 Hz`
- NanoOWL `/output_detections`: about `14.5 Hz`
- `/object_position`: about `14.6 Hz`
- `/ackermann_cmd`: about `20.0 Hz`

### Safety State

- `/ackermann_cmd` remained:
  - `speed: 0.0`
  - `steering_angle: 0.0`
- `vesc_driver_node` was not connected to `/dev/ttyACM0`, so there was no active VESC motor link

### Resource Profile

- NanoOWL process:
  - about `48.4%` CPU
  - about `1.72 GB` RSS
- RealSense node:
  - about `9.4%` CPU
  - about `183 MB` RSS
- `object_position_node`:
  - about `8.4%` CPU
  - about `148 MB` RSS
- `joy_node`:
  - about `14.3%` CPU
- `control_center_node`:
  - about `1.3%` CPU
- Jetson-wide:
  - RAM about `4.9 / 7.6 GB`
  - GR3D about `6%` to `95%`
  - all CPU cores often close to saturation

### Interpretation

This configuration is viable. NanoOWL stays on GPU and the control stack remains alive, but the system is already CPU-heavy. The camera stream slows below its nominal `15 Hz`, while NanoOWL still produces detections fast enough for perception use.

## Configuration B: GPU NanoOWL + Camera + Object Position + Control Stack + LiDAR + LiDAR Localization

### Additional Active Components

- `sllidar_node`
- `lidar_transformer_node`
- `lidar_localization_node`

### Verification

- `/scan` was live at about `10.0 Hz`
- `/pcl_pose` published a real pose
- `/ackermann_cmd` remained a zero-speed stop command
- NanoOWL continued publishing `/output_detections`
- `object_position_node` continued publishing `/object_position`

Example `/pcl_pose` during this run:

- `x = -0.3067`
- `y = -0.7730`

Example `/object_position` during this run:

- `x = 1.555 m`
- `y = 0.0325 m`

### Measured Runtime

- `/scan`: about `10.0 Hz`
- `/ackermann_cmd`: about `20.0 Hz`
- `/object_position`: stabilized around `14.6` to `14.8 Hz`
- NanoOWL `/output_detections`: about `15.0 Hz`

### Resource Profile

- `lidar_transformer_node`:
  - about `51.5%` CPU
  - about `61.7 MB` RSS
- NanoOWL GPU node:
  - about `48.2%` CPU
  - about `1.72 GB` RSS
- `lidar_localization_node`:
  - about `6.6%` CPU
  - about `54.6 MB` RSS
- `sllidar_node`:
  - about `10.6%` CPU
  - about `20.8 MB` RSS
- RealSense node:
  - about `9.4%` CPU
  - about `183.7 MB` RSS
- `object_position_node`:
  - about `8.4%` CPU
  - about `149.1 MB` RSS
- `f1tenth_container`:
  - about `17.2%` CPU
  - about `167 MB`
- `nanoowl-eval-container`:
  - about `47.1%` CPU
  - about `1.39 GB`
- Jetson-wide:
  - RAM about `5.0 / 7.6 GB`
  - SWAP about `1.68 GB`
  - GR3D about `45%` to `87%`
  - board power about `11.5W` to `11.8W`

### Important Observation

The biggest new CPU consumer after reintroducing LiDAR localization was not NanoOWL itself. It was `lidar_transformer_node`, which consumed about `51.5%` CPU in this run.

### Interpretation

This full stack is still viable on GPU for NanoOWL when the perception path is kept light:

- low-resolution camera
- low frame rate
- no annotated image publishing
- TensorRT engine enabled

The system remains near its practical limit, but it does not collapse. NanoOWL continues to operate on GPU while LiDAR localization and the control stack are active.

## What Is And Is Not Available

### Available

- GPU NanoOWL with TensorRT in the live ADAONE stack
- Depth-based object position estimation from camera detections
- LiDAR-based vehicle localization
- Safe stop-state control path

### Not Available

- A camera-only vehicle localization stack in this repository

The current localization package is LiDAR-specific:

- `/home/ada2/CARKit/src/lidar_localization_ros2/launch/lidar_localization.launch.py`
- `/home/ada2/CARKit/src/lidar_localization_ros2/param/localization.yaml`

That path expects a point cloud on `/cloud_in` and a PCD map. The depth camera is currently used for object-relative position estimation, not full vehicle localization.

## Final Conclusion

### Model Evaluation

- The fine-tuned model is slightly more accurate on COCO.
- The baseline model is still faster.

### Deployment Evaluation

- NanoOWL does run on GPU with the required packages launched.
- It is not necessary to fall back to CPU if the stack is configured carefully.
- The successful deployment recipe is:
  - `device:=cuda`
  - TensorRT engine enabled
  - `publish_output_image:=false`
  - reduced RealSense profile (`640x480@15`)

### Practical Takeaway

The Jetson Orin Nano can support:

- NanoOWL on GPU
- F1TENTH low-level/control stack
- depth-based object localization
- LiDAR localization

at the same time, but only when the perception stack is kept in a resource-aware edge mode.
