from __future__ import annotations

import argparse
import json
from pathlib import Path

from nightwatch.datasets import dataset_sha256
from nightwatch.scam_classifier import (
    SCAM_CLASSIFIER_PIPELINE_VERSION,
    SCAM_EVALUATION_BATCH_SIZE,
    SCAM_ID_TO_LABEL,
    SCAM_LABEL_TO_ID,
    initialize_scam_training_seed,
    scam_classification_metrics,
    scam_classifier_text,
)
from nightwatch.scam_safety import (
    assert_no_scam_eval_leakage,
    load_scam_curriculum,
    load_scam_eval_cases,
    load_scam_mission,
)
from nightwatch.train_classifier import audit_trainable_parameters


def train_scam_classifier(
    mission_path: Path,
    curriculum_path: Path,
    development_path: Path,
    output_dir: Path,
    *,
    rank: int,
    epochs: float,
    learning_rate: float,
    seed: int,
    selection_metric: str = "macro_f1",
) -> dict[str, object]:
    try:
        import numpy as np
        import torch
        from datasets import Dataset
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
            set_seed,
        )
    except ImportError as exc:
        raise SystemExit("Training dependencies are missing. Run: uv sync --extra train") from exc

    initialize_scam_training_seed(seed, set_seed)
    mission = load_scam_mission(mission_path)
    curriculum = load_scam_curriculum(curriculum_path)
    development = load_scam_eval_cases(development_path)
    assert_no_scam_eval_leakage(curriculum, development)
    train_dataset = Dataset.from_list(
        [
            {
                "text": scam_classifier_text(row["message"], mission),
                "label": SCAM_LABEL_TO_ID[row["label"]],
            }
            for row in curriculum
        ]
    )
    development_dataset = Dataset.from_list(
        [
            {
                "text": scam_classifier_text(case.message, mission),
                "label": SCAM_LABEL_TO_ID[case.expected_label],
            }
            for case in development
        ]
    )
    tokenizer = AutoTokenizer.from_pretrained(
        mission.model_id,
        revision=mission.model_revision,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    def tokenize(batch: dict[str, list[object]]) -> dict[str, object]:
        return tokenizer(batch["text"], truncation=True, max_length=256)

    train_dataset = train_dataset.map(tokenize, batched=True, remove_columns=["text"])
    development_dataset = development_dataset.map(
        tokenize,
        batched=True,
        remove_columns=["text"],
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        mission.model_id,
        revision=mission.model_revision,
        num_labels=len(SCAM_LABEL_TO_ID),
        id2label=SCAM_ID_TO_LABEL,
        label2id=SCAM_LABEL_TO_ID,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )
    model.config.pad_token_id = tokenizer.pad_token_id
    model.config.use_cache = False
    model = get_peft_model(
        model,
        LoraConfig(
            task_type=TaskType.SEQ_CLS,
            r=rank,
            lora_alpha=2 * rank,
            lora_dropout=0.05,
            bias="none",
            target_modules=["q_proj", "v_proj"],
            modules_to_save=["score"],
        ),
    )
    trainable_parameters = audit_trainable_parameters(model.named_parameters())

    def compute_metrics(eval_prediction: object) -> dict[str, float]:
        predicted = np.argmax(eval_prediction.predictions, axis=-1).tolist()
        expected = eval_prediction.label_ids.tolist()
        return scam_classification_metrics(expected, predicted)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        learning_rate=learning_rate,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=SCAM_EVALUATION_BATCH_SIZE,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model=selection_metric,
        greater_is_better=True,
        save_total_limit=1,
        logging_steps=5,
        report_to="none",
        seed=seed,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=development_dataset,
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
    )
    result = trainer.train()
    development_metrics = trainer.evaluate()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    manifest: dict[str, object] = {
        "mission_id": mission.mission_id,
        "model_id": mission.model_id,
        "model_revision": mission.model_revision,
        "pipeline_version": SCAM_CLASSIFIER_PIPELINE_VERSION,
        "labels": SCAM_LABEL_TO_ID,
        "mission_sha256": dataset_sha256(mission_path),
        "curriculum_sha256": dataset_sha256(curriculum_path),
        "development_sha256": dataset_sha256(development_path),
        "examples": len(curriculum),
        "rank": rank,
        "epochs": epochs,
        "learning_rate": learning_rate,
        "seed": seed,
        "selection_metric": selection_metric,
        "trainable_parameters": trainable_parameters,
        "train_runtime": result.metrics.get("train_runtime"),
        "development_metrics": {
            key: float(value)
            for key, value in development_metrics.items()
            if isinstance(value, (int, float))
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "nightwatch-scam-training.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Nightwatch Gemma scam-safety classifier")
    parser.add_argument(
        "--mission",
        type=Path,
        default=Path("data/scam_safety/mission.json"),
    )
    parser.add_argument("--curriculum", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--selection-metric", choices=("macro_f1", "accuracy"), default="macro_f1")
    args = parser.parse_args()
    if args.rank not in {4, 8, 16}:
        raise SystemExit("--rank must be 4, 8, or 16")
    train_scam_classifier(
        args.mission,
        args.curriculum,
        args.development,
        args.output_dir,
        rank=args.rank,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        seed=args.seed,
        selection_metric=args.selection_metric,
    )


if __name__ == "__main__":
    main()
