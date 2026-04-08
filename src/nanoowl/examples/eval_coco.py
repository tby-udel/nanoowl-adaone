#!/usr/bin/env python3

import argparse
import json
import time
from pathlib import Path
from typing import Optional

from PIL import Image
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval

from nanoowl.owl_predictor import OwlPredictor

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ENGINE_PATH = SCRIPT_DIR.parent / "data" / "owl_image_encoder_patch32.engine"


STAT_NAMES = [
    "AP",
    "AP50",
    "AP75",
    "AP_small",
    "AP_medium",
    "AP_large",
    "AR_max1",
    "AR_max10",
    "AR_max100",
    "AR_small",
    "AR_medium",
    "AR_large",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate NanoOWL on COCO 2017 validation images."
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        required=True,
        help="Path to instances_val2017.json",
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        required=True,
        help="Path to COCO val2017 image directory",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="google/owlvit-base-patch32",
        help="Hugging Face model id or local model directory",
    )
    parser.add_argument(
        "--image-encoder-engine",
        type=str,
        default=str(DEFAULT_ENGINE_PATH),
        help='Path to the NanoOWL TensorRT engine, or "none" to disable TensorRT',
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda",
        choices=["cuda", "cpu"],
        help="Inference device",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.1,
        help="Detection threshold applied to every COCO category prompt",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="Optional limit on the number of images to evaluate; 0 means full val2017",
    )
    parser.add_argument(
        "--prompt-template",
        type=str,
        default="a photo of {label}",
        help="Prompt template used for COCO category names",
    )
    parser.add_argument(
        "--pad-square",
        action="store_true",
        help="Enable NanoOWL square padding before inference",
    )
    parser.add_argument(
        "--results-json",
        type=Path,
        default=Path("coco_results_baseline.json"),
        help="Where to write COCO-format detections",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=Path("coco_summary_baseline.json"),
        help="Where to write summarized COCO metrics",
    )
    return parser.parse_args()


def resolve_engine_path(engine_arg: str) -> Optional[Path]:
    if engine_arg is None:
        return None

    value = str(engine_arg).strip()
    if value.lower() in {"", "none", "null", "off"}:
        return None

    return Path(value).resolve()


def build_prompts(categories, prompt_template):
    prompts = []
    for category in categories:
        label = category["name"]
        prompts.append(prompt_template.format(label=label))
    return prompts


def main():
    args = parse_args()

    args.annotations = args.annotations.resolve()
    args.image_dir = args.image_dir.resolve()
    args.results_json = args.results_json.resolve()
    args.summary_json = args.summary_json.resolve()
    engine_path = resolve_engine_path(args.image_encoder_engine)

    if not args.annotations.exists():
        raise FileNotFoundError(f"Missing annotations file: {args.annotations}")
    if not args.image_dir.exists():
        raise FileNotFoundError(f"Missing image directory: {args.image_dir}")
    if args.device == "cuda" and engine_path is not None and not engine_path.exists():
        raise FileNotFoundError(
            f"Missing TensorRT engine: {engine_path}"
        )

    coco = COCO(str(args.annotations))
    categories = sorted(coco.loadCats(coco.getCatIds()), key=lambda cat: cat["id"])
    prompts = build_prompts(categories, args.prompt_template)
    label_to_category_id = [category["id"] for category in categories]

    predictor_kwargs = {"device": args.device}
    if args.device == "cuda" and engine_path is not None:
        predictor_kwargs["image_encoder_engine"] = str(engine_path)
    predictor = OwlPredictor(args.model, **predictor_kwargs)
    backend = "cuda_trt" if args.device == "cuda" and engine_path is not None else f"{args.device}_torch"

    print("Loaded model:", args.model)
    print("Using device:", args.device)
    print("Using backend:", backend)
    print("Using engine:", engine_path if engine_path is not None else "none")
    print("Prompt template:", args.prompt_template)
    print("Threshold:", args.threshold)

    text_encodings = predictor.encode_text(prompts)

    image_ids = sorted(coco.getImgIds())
    if args.max_images > 0:
        image_ids = image_ids[: args.max_images]

    print("Number of categories:", len(categories))
    print("Number of images:", len(image_ids))

    detections = []
    start_time = time.perf_counter()

    for index, image_id in enumerate(image_ids, start=1):
        image_info = coco.loadImgs([image_id])[0]
        image_path = args.image_dir / image_info["file_name"]
        if not image_path.exists():
            raise FileNotFoundError(f"Missing COCO image: {image_path}")

        with Image.open(image_path) as image:
            image = image.convert("RGB")
            output = predictor.predict(
                image=image,
                text=prompts,
                text_encodings=text_encodings,
                threshold=args.threshold,
                pad_square=args.pad_square,
            )

        boxes = output.boxes.detach().cpu().tolist()
        labels = output.labels.detach().cpu().tolist()
        scores = output.scores.detach().cpu().tolist()

        for box, label_index, score in zip(boxes, labels, scores):
            x0, y0, x1, y1 = [float(value) for value in box]
            width = max(0.0, x1 - x0)
            height = max(0.0, y1 - y0)
            if width <= 0.0 or height <= 0.0:
                continue

            detections.append(
                {
                    "image_id": image_id,
                    "category_id": label_to_category_id[int(label_index)],
                    "bbox": [x0, y0, width, height],
                    "score": float(score),
                }
            )

        if index == 1 or index % 50 == 0 or index == len(image_ids):
            elapsed = time.perf_counter() - start_time
            print(
                f"[{index}/{len(image_ids)}] "
                f"detections={len(detections)} "
                f"elapsed={elapsed:.1f}s "
                f"avg_per_image={elapsed / index:.3f}s"
            )

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)

    with args.results_json.open("w", encoding="utf-8") as f:
        json.dump(detections, f)

    coco_dt = coco.loadRes(str(args.results_json))
    coco_eval = COCOeval(coco, coco_dt, "bbox")
    coco_eval.params.imgIds = image_ids
    coco_eval.params.catIds = label_to_category_id
    coco_eval.evaluate()
    coco_eval.accumulate()
    coco_eval.summarize()

    elapsed = time.perf_counter() - start_time
    summary = {
        "model": args.model,
        "device": args.device,
        "backend": backend,
        "image_encoder_engine": str(engine_path) if engine_path is not None else None,
        "annotations": str(args.annotations),
        "image_dir": str(args.image_dir),
        "prompt_template": args.prompt_template,
        "threshold": args.threshold,
        "pad_square": args.pad_square,
        "num_categories": len(categories),
        "num_images": len(image_ids),
        "num_detections": len(detections),
        "total_seconds": elapsed,
        "avg_seconds_per_image": elapsed / max(1, len(image_ids)),
        "stats": {
            name: float(value) for name, value in zip(STAT_NAMES, coco_eval.stats)
        },
    }

    with args.summary_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\nSaved detections to:", args.results_json)
    print("Saved summary to:", args.summary_json)
    print(json.dumps(summary["stats"], indent=2))


if __name__ == "__main__":
    main()
