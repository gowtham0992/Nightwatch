from __future__ import annotations

import argparse
import json
from pathlib import Path

from nightwatch.scam_classifier import (
    SCAM_CLASSIFIER_PIPELINE_VERSION,
    SCAM_EVALUATION_BATCH_SIZE,
    SCAM_ID_TO_LABEL,
    SCAM_LABEL_TO_ID,
    scam_classifier_text,
)
from nightwatch.scam_safety import load_scam_eval_cases, load_scam_mission


def _validate_prediction_batch_size(batch_size: int) -> int:
    if not 1 <= batch_size <= 64:
        raise ValueError("batch_size must be between 1 and 64")
    return batch_size


def _validate_adapter_manifest(adapter_path: Path, mission_id: str, model_id: str, revision: str) -> None:
    manifest_path = adapter_path / "nightwatch-scam-training.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("adapter is missing a valid Nightwatch scam training manifest") from exc
    expected = {
        "mission_id": mission_id,
        "model_id": model_id,
        "model_revision": revision,
        "labels": SCAM_LABEL_TO_ID,
        "pipeline_version": SCAM_CLASSIFIER_PIPELINE_VERSION,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("adapter manifest does not match the scam mission contract")


def predict_scam_classifier(
    mission_path: Path,
    adapter_path: Path,
    eval_path: Path,
    output_path: Path,
    *,
    batch_size: int = SCAM_EVALUATION_BATCH_SIZE,
) -> None:
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise SystemExit("Inference dependencies are missing. Run: uv sync --extra train") from exc

    _validate_prediction_batch_size(batch_size)
    mission = load_scam_mission(mission_path)
    _validate_adapter_manifest(
        adapter_path,
        mission.mission_id,
        mission.model_id,
        mission.model_revision,
    )
    cases = load_scam_eval_cases(eval_path)
    tokenizer = AutoTokenizer.from_pretrained(
        mission.model_id,
        revision=mission.model_revision,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForSequenceClassification.from_pretrained(
        mission.model_id,
        revision=mission.model_revision,
        num_labels=len(SCAM_LABEL_TO_ID),
        id2label=SCAM_ID_TO_LABEL,
        label2id=SCAM_LABEL_TO_ID,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )
    base.config.pad_token_id = tokenizer.pad_token_id
    model = PeftModel.from_pretrained(base, str(adapter_path))
    model.eval()

    rows: list[dict[str, object]] = []
    for start in range(0, len(cases), batch_size):
        batch_cases = cases[start : start + batch_size]
        encoded = tokenizer(
            [scam_classifier_text(case.message, mission) for case in batch_cases],
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        ).to(model.device)
        with torch.inference_mode():
            probabilities = torch.softmax(model(**encoded).logits.float(), dim=-1)
        for case, scores in zip(batch_cases, probabilities, strict=True):
            label_id = int(scores.argmax().item())
            rows.append(
                {
                    "id": case.case_id,
                    "label": SCAM_ID_TO_LABEL[label_id],
                    "confidence": round(float(scores[label_id].item()), 6),
                }
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict with a Nightwatch Gemma scam classifier")
    parser.add_argument(
        "--mission",
        type=Path,
        default=Path("data/scam_safety/mission.json"),
    )
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=SCAM_EVALUATION_BATCH_SIZE)
    args = parser.parse_args()
    predict_scam_classifier(
        args.mission,
        args.adapter,
        args.eval,
        args.output,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
