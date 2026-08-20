from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

import modal

from nightwatch.modal_v0 import ARTIFACT_ROOT, HF_CACHE_ROOT, experiment_artifacts, hf_cache, hf_secret, image

app = modal.App("nightwatch-generic")


@app.function(image=image)
def preflight_generic_classifier() -> dict[str, Any]:
    """Import the exact generic runtime modules without allocating a GPU."""

    from nightwatch.generic_evaluation import evaluate_predictions
    from nightwatch.operator_contracts import REGISTERED_BASELINES, parse_uploaded_dataset

    if not callable(evaluate_predictions) or not callable(parse_uploaded_dataset):
        raise RuntimeError("generic classifier runtime imports are incomplete")
    return {
        "status": "ready",
        "registered_baselines": sorted(REGISTERED_BASELINES),
    }


def _input_digest(operation: str, contract_json: str, dataset_jsonl: str, curriculum_jsonl: str | None) -> str:
    return hashlib.sha256("\n".join((operation, contract_json, dataset_jsonl, curriculum_jsonl or "")).encode()).hexdigest()


@app.function(
    image=image,
    gpu="L4",
    timeout=25 * 60,
    secrets=[hf_secret],
    volumes={str(HF_CACHE_ROOT): hf_cache, str(ARTIFACT_ROOT): experiment_artifacts},
)
def run_generic_classifier(
    operation: str,
    contract_json: str,
    dataset_jsonl: str,
    curriculum_jsonl: str | None,
) -> dict[str, Any]:
    """Evaluate a registered adapter or train exactly one PEFT candidate."""

    import numpy as np
    import torch
    from datasets import Dataset
    from peft import LoraConfig, PeftConfig, PeftModel, TaskType, get_peft_model
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments, set_seed

    from nightwatch.generic_evaluation import evaluate_predictions, validate_predictions
    from nightwatch.operator_contracts import REGISTERED_BASELINES, mission_contract_from_dict, parse_uploaded_dataset, revalidate_contract
    from nightwatch.train_classifier import audit_trainable_parameters

    if operation not in {"baseline", "candidate"}:
        raise ValueError("operation must be baseline or candidate")
    if any(len(value.encode()) > 5_000_000 for value in (contract_json, dataset_jsonl, curriculum_jsonl or "")):
        raise ValueError("generic classifier input exceeds the bounded payload limit")
    contract = mission_contract_from_dict(json.loads(contract_json))
    dataset = parse_uploaded_dataset(dataset_jsonl.encode(), "jsonl")
    revalidate_contract(contract, dataset)
    input_sha = _input_digest(operation, contract_json, dataset_jsonl, curriculum_jsonl)
    labels = list(contract.labels)
    label_to_id = {label: index for index, label in enumerate(labels)}
    id_to_label = {index: label for label, index in label_to_id.items()}

    work = Path(f"/tmp/nightwatch-generic-{operation}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    output = work / "adapter"
    set_seed(contract.compute.seed, deterministic=True)

    baseline_spec = REGISTERED_BASELINES[contract.baseline_artifact]

    def prompt(text: object) -> str:
        normalized = str(text).strip()
        if baseline_spec["prompt_style"] == "scam_message":
            return f"{contract.instruction}\n\nMessage:\n{normalized}"
        if baseline_spec["prompt_style"] == "production_alert":
            from nightwatch.classifier import classifier_text
            return classifier_text(normalized)
        raise ValueError("registered baseline prompt style is unsupported")

    eval_rows = [
        {
            "id": str(row[contract.mapping.id_column]).strip(),
            "text": prompt(row[contract.mapping.text_column]),
            "label": label_to_id[str(row[contract.mapping.label_column]).strip()],
        }
        for row in dataset.rows
    ]
    started = time.monotonic()
    training: dict[str, Any] | None = None
    if operation == "baseline":
        adapter = ARTIFACT_ROOT / "adapters" / contract.baseline_artifact
        if not adapter.is_dir():
            raise FileNotFoundError("registered baseline adapter does not exist")
        if contract.baseline_artifact.startswith("scam-"):
            from nightwatch.scam_safety import SCAM_LABELS
            expected_adapter_labels = set(SCAM_LABELS)
            manifest_path = adapter / "nightwatch-scam-training.json"
        elif contract.baseline_artifact.startswith("classifier-"):
            from nightwatch.classifier import CLASSIFIER_LABELS
            expected_adapter_labels = set(CLASSIFIER_LABELS)
            manifest_path = adapter / "nightwatch-classifier-training.json"
        else:
            raise ValueError("baseline adapter family is not registered")
        if set(labels) != expected_adapter_labels:
            raise ValueError("dataset labels do not match the registered baseline adapter")
        if not manifest_path.is_file():
            raise FileNotFoundError("baseline adapter manifest does not exist")
        adapter_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            adapter_manifest.get("model_id") != contract.model_id
            or adapter_manifest.get("model_revision") != contract.model_revision
        ):
            raise ValueError("baseline adapter manifest is bound to a different checkpoint")
        peft_config = PeftConfig.from_pretrained(adapter)
        if peft_config.base_model_name_or_path != contract.model_id:
            raise ValueError("baseline adapter is bound to a different base model")
        tokenizer = AutoTokenizer.from_pretrained(adapter)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForSequenceClassification.from_pretrained(
            contract.model_id,
            revision=contract.model_revision,
            num_labels=len(labels),
            id2label=id_to_label,
            label2id=label_to_id,
            dtype=torch.bfloat16,
            device_map="auto",
        )
        model = PeftModel.from_pretrained(model, adapter)
        artifact_name = contract.baseline_artifact
    else:
        if not curriculum_jsonl:
            raise ValueError("candidate training requires authored curriculum")
        authored = [json.loads(line) for line in curriculum_jsonl.splitlines() if line.strip()]
        if not 24 <= len(authored) <= 48 or any(set(row) != {"label", "specialist", "text"} or row["label"] not in label_to_id for row in authored):
            raise ValueError("candidate curriculum violates the bounded schema")
        tokenizer = AutoTokenizer.from_pretrained(contract.model_id, revision=contract.model_revision)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForSequenceClassification.from_pretrained(
            contract.model_id,
            revision=contract.model_revision,
            num_labels=len(labels),
            id2label=id_to_label,
            label2id=label_to_id,
            dtype=torch.bfloat16,
            device_map="auto",
        )
        model = get_peft_model(model, LoraConfig(
            task_type=TaskType.SEQ_CLS,
            r=contract.compute.rank,
            lora_alpha=2 * contract.compute.rank,
            lora_dropout=0.05,
            bias="none",
            target_modules=["q_proj", "v_proj"],
            modules_to_save=["score"],
        ))
        trainable = audit_trainable_parameters(model.named_parameters())
        train_rows = [{"text": prompt(row["text"]), "label": label_to_id[row["label"]]} for row in authored]
        train_dataset = Dataset.from_list(train_rows)

        def tokenize(batch: dict[str, list[object]]) -> dict[str, object]:
            return tokenizer(batch["text"], truncation=True, max_length=256)

        train_dataset = train_dataset.map(tokenize, batched=True, remove_columns=["text"])
        args = TrainingArguments(
            output_dir=str(output),
            num_train_epochs=contract.compute.epochs,
            learning_rate=contract.compute.learning_rate,
            per_device_train_batch_size=8,
            save_strategy="no",
            report_to="none",
            seed=contract.compute.seed,
        )
        trainer = Trainer(model=model, args=args, train_dataset=train_dataset, processing_class=tokenizer)
        result = trainer.train()
        trainer.save_model(str(output))
        tokenizer.save_pretrained(str(output))
        artifact_name = f"candidate-{contract.contract_id.removeprefix('contract-')}-{input_sha[:10]}"
        persistent = ARTIFACT_ROOT / "adapters" / artifact_name
        if persistent.exists():
            raise RuntimeError("immutable candidate adapter already exists")
        persistent.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(output, persistent)
        experiment_artifacts.commit()
        training = {
            "examples": len(authored),
            "runtime_seconds": result.metrics.get("train_runtime"),
            "trainable_parameters": trainable,
            "attempt": 1,
        }

    model.config.pad_token_id = tokenizer.pad_token_id
    model.eval()
    predictions: list[dict[str, object]] = []
    for row in eval_rows:
        encoded = tokenizer(row["text"], return_tensors="pt", truncation=True, max_length=256).to(model.device)
        with torch.no_grad():
            probabilities = torch.softmax(model(**encoded).logits[0].float(), dim=-1).cpu().numpy()
        selected = int(np.argmax(probabilities))
        predictions.append({"id": row["id"], "label": id_to_label[selected], "confidence": float(probabilities[selected])})
    validated = validate_predictions(predictions, contract, dataset)
    evaluation = evaluate_predictions(artifact_name, validated, contract, dataset)
    return {
        "operation": operation,
        "contract_id": contract.contract_id,
        "input_sha256": input_sha,
        "artifact_name": artifact_name,
        "predictions": predictions,
        "evaluation": evaluation,
        "training": training,
        "runtime_seconds": time.monotonic() - started,
    }
