# Corrected Fine-Tuned Engine Comparison

Generated: 2026-04-09 EDT

## Scope

This note captures the corrected comparison after rebuilding the fine-tuned OWL-ViT image encoder with a stock-style TensorRT path.

Compared runs:

- baseline model with baseline engine:
  - `eval/coco/coco_summary_baseline_full_cuda_trt.json`
- fine-tuned model with the older slower engine:
  - `eval/coco/coco_summary_owlvit_deal_imagenet_step55_full_cuda_trt_fp16.json`
- fine-tuned model with the corrected fast engine:
  - `eval/coco/coco_summary_owlvit_deal_imagenet_step55_full_cuda_trt_stock_opset17.json`

## What Changed

The earlier fine-tuned engine was a bad deployment artifact, not proof that the fine-tuned checkpoint itself was inherently slow.

The corrected engine was rebuilt with the same plain TensorRT style as the original NanoOWL engine:

- FP16 enabled
- fixed `1x3x768x768` input shape
- no weight streaming
- no low-memory rescue flags

The only necessary difference was exporting ONNX with opset `17`, which gave TensorRT a cleaner graph for this checkpoint on this Jetson.

## Full COCO 2017 `val2017` Results

### Baseline vs Corrected Fine-Tuned Engine

| Metric | Baseline | Fine-tuned corrected engine | Delta |
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
| Detections | 39475 | 36274 | -3201 |
| Seconds / image | 0.0954 | 0.1050 | +0.0096 |
| Images / second | 10.48 | 9.52 | -0.96 |

### Interpretation

- The corrected fine-tuned engine keeps the fine-tuned model slightly ahead on precision:
  - `AP +0.0031`
  - `AP75 +0.0041`
  - `AP_large +0.0086`
- The fine-tuned model still trades away some recall:
  - `AR@100 -0.0070`
- Small-object performance is slightly worse than baseline:
  - `AP_small -0.0008`
- The speed penalty is now small enough to be practical on this Jetson:
  - baseline: `10.48 img/s`
  - corrected fine-tuned engine: `9.52 img/s`

## Old Fine-Tuned Engine vs Corrected Fine-Tuned Engine

| Metric | Older fine-tuned engine | Corrected fine-tuned engine | Delta |
| --- | ---: | ---: | ---: |
| AP | 0.2527 | 0.2517 | -0.0010 |
| AP50 | 0.3972 | 0.3955 | -0.0016 |
| AP75 | 0.2687 | 0.2676 | -0.0012 |
| AP small | 0.0892 | 0.0894 | +0.0002 |
| AP medium | 0.2592 | 0.2590 | -0.0002 |
| AP large | 0.4409 | 0.4380 | -0.0028 |
| AR@100 | 0.3525 | 0.3510 | -0.0015 |
| Seconds / image | 0.1640 | 0.1050 | -0.0590 |
| Images / second | 6.10 | 9.52 | +3.43 |

### Interpretation

- Accuracy changed only slightly.
- Runtime improved dramatically.
- The corrected engine is about `1.56x` faster than the older fine-tuned engine on full COCO evaluation.

## Raw Engine Benchmark

Direct `trtexec` checks showed the engine difference clearly:

- baseline engine:
  - about `11.21 qps`
  - mean GPU compute `89.16 ms`
- older fine-tuned engine:
  - about `3.70 qps`
  - mean GPU compute `270.35 ms`
- corrected fine-tuned engine:
  - about `26.62 qps`
  - mean GPU compute `37.56 ms`

That confirms the earlier slowdown was caused by a poor engine build path, not simply by the fine-tuned checkpoint itself.

## Files Produced

- `eval/coco/coco_results_owlvit_deal_imagenet_step55_full_cuda_trt_stock_opset17.json`
- `eval/coco/coco_summary_owlvit_deal_imagenet_step55_full_cuda_trt_stock_opset17.json`
- `src/nanoowl/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`
- `src/ROS2-NanoOWL/data/owlvit_deal_imagenet_step55_hf_image_encoder_stock_opset17.engine`

## Bottom Line

The corrected stock-style opset-17 TensorRT engine fixes the unacceptable slowdown.

Compared with baseline:

- accuracy is still slightly better overall
- large-object precision remains better
- runtime is now close to baseline instead of dramatically worse

This corrected engine is the right default deployment artifact for the fine-tuned model on this Jetson.
