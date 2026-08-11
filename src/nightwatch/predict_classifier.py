from __future__ import annotations

import argparse
import json
from pathlib import Path

from nightwatch.classifier import CLASSIFIER_LABELS, ID_TO_LABEL, LABEL_TO_ID, classifier_text
from nightwatch.datasets import load_eval_cases
from nightwatch.model_config import GEMMA_MODEL_ID, GEMMA_MODEL_REVISION


def predict_classifier(
    adapter_path: Path,
    eval_path: Path,
    output_path: Path,
    *,
    model_id: str = GEMMA_MODEL_ID,
    model_revision: str = GEMMA_MODEL_REVISION,
) -> None:
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise SystemExit("Inference dependencies are missing. Run: uv sync --extra train") from exc

    cases = load_eval_cases(eval_path)
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=model_revision)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForSequenceClassification.from_pretrained(
        model_id,
        revision=model_revision,
        num_labels=len(CLASSIFIER_LABELS),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )
    base.config.pad_token_id = tokenizer.pad_token_id
    model = PeftModel.from_pretrained(base, str(adapter_path))
    model.eval()

    rows: list[dict[str, object]] = []
    batch_size = 32
    for start in range(0, len(cases), batch_size):
        batch_cases = cases[start : start + batch_size]
        encoded = tokenizer(
            [classifier_text(case.prompt) for case in batch_cases],
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
                    "label": ID_TO_LABEL[label_id],
                    "confidence": round(float(scores[label_id].item()), 6),
                }
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict with a Nightwatch Gemma sequence-classifier adapter")
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--eval", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    predict_classifier(args.adapter, args.eval, args.output)


if __name__ == "__main__":
    main()
