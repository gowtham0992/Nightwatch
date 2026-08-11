from __future__ import annotations

import argparse
import json
from pathlib import Path

from nightwatch.classifier import (
    CLASSIFIER_PIPELINE_VERSION,
    CLASSIFIER_LABELS,
    ID_TO_LABEL,
    LABEL_TO_ID,
    classification_metrics,
    classifier_text,
)
from nightwatch.datasets import dataset_sha256, load_curriculum, load_eval_cases
from nightwatch.model_config import GEMMA_MODEL_ID, GEMMA_MODEL_REVISION


def audit_trainable_parameters(named_parameters: object) -> dict[str, object]:
    """Fail closed unless both the LoRA adapters and classifier head will train."""
    trainable = [
        (name, parameter)
        for name, parameter in named_parameters
        if parameter.requires_grad
    ]
    lora = [(name, parameter) for name, parameter in trainable if "lora_" in name]
    head = [(name, parameter) for name, parameter in trainable if "score" in name]
    if not lora:
        raise RuntimeError("no trainable LoRA parameters were found")
    if not head:
        raise RuntimeError("the sequence-classification score head is frozen")
    return {
        "total": sum(parameter.numel() for _, parameter in trainable),
        "lora": sum(parameter.numel() for _, parameter in lora),
        "score_head": sum(parameter.numel() for _, parameter in head),
        "names": [name for name, _ in trainable],
    }


def train_classifier(
    curriculum_path: Path,
    dev_path: Path,
    output_dir: Path,
    *,
    rank: int,
    epochs: float,
    learning_rate: float,
    seed: int,
    model_id: str = GEMMA_MODEL_ID,
    model_revision: str = GEMMA_MODEL_REVISION,
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
        )
    except ImportError as exc:
        raise SystemExit("Training dependencies are missing. Run: uv sync --extra train") from exc

    curriculum = load_curriculum(curriculum_path)
    dev_cases = load_eval_cases(dev_path)
    train_dataset = Dataset.from_list(
        [
            {"text": classifier_text(row["prompt"]), "label": LABEL_TO_ID[row["label"]]}
            for row in curriculum
        ]
    )
    dev_dataset = Dataset.from_list(
        [
            {"text": classifier_text(case.prompt), "label": LABEL_TO_ID[case.expected_label]}
            for case in dev_cases
        ]
    )
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=model_revision)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    def tokenize(batch: dict[str, list[object]]) -> dict[str, object]:
        return tokenizer(batch["text"], truncation=True, max_length=256)

    train_dataset = train_dataset.map(tokenize, batched=True, remove_columns=["text"])
    dev_dataset = dev_dataset.map(tokenize, batched=True, remove_columns=["text"])
    model = AutoModelForSequenceClassification.from_pretrained(
        model_id,
        revision=model_revision,
        num_labels=len(CLASSIFIER_LABELS),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
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
        predictions = np.argmax(eval_prediction.predictions, axis=-1).tolist()
        labels = eval_prediction.label_ids.tolist()
        return classification_metrics(labels, predictions)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        learning_rate=learning_rate,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=16,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
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
        eval_dataset=dev_dataset,
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
    )
    result = trainer.train()
    dev_metrics = trainer.evaluate()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    manifest: dict[str, object] = {
        "model_id": model_id,
        "model_revision": model_revision,
        "pipeline_version": CLASSIFIER_PIPELINE_VERSION,
        "curriculum_sha256": dataset_sha256(curriculum_path),
        "dev_sha256": dataset_sha256(dev_path),
        "examples": len(curriculum),
        "rank": rank,
        "epochs": epochs,
        "learning_rate": learning_rate,
        "seed": seed,
        "trainable_parameters": trainable_parameters,
        "train_runtime": result.metrics.get("train_runtime"),
        "dev_metrics": {key: float(value) for key, value in dev_metrics.items() if isinstance(value, (int, float))},
    }
    (output_dir / "nightwatch-classifier-training.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the Nightwatch Gemma sequence classifier")
    parser.add_argument("--curriculum", type=Path, default=Path("artifacts/v0-curriculum.jsonl"))
    parser.add_argument("--dev", type=Path, default=Path("artifacts/v0-dev.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/v0-classifier"))
    parser.add_argument("--rank", type=int, default=4)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--seed", type=int, default=20260809)
    args = parser.parse_args()
    train_classifier(
        args.curriculum,
        args.dev,
        args.output_dir,
        rank=args.rank,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
