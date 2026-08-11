from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from nightwatch.modal_v0 import (
    ARTIFACT_ROOT,
    HF_CACHE_ROOT,
    _bounded_payload,
    app,
    experiment_artifacts,
    hf_cache,
    hf_secret,
    image,
)
from nightwatch.model_config import (
    GEMMA_MODEL_ID,
    GEMMA_MODEL_REVISION,
    validate_gemma_checkpoint,
)


@app.function(
    image=image,
    gpu="L4",
    timeout=30 * 60,
    secrets=[hf_secret],
    volumes={
        str(HF_CACHE_ROOT): hf_cache,
        str(ARTIFACT_ROOT): experiment_artifacts,
    },
)
def train_classifier_arm(
    curriculum_jsonl: str,
    dev_jsonl: str,
    *,
    model_id: str = GEMMA_MODEL_ID,
    model_revision: str = GEMMA_MODEL_REVISION,
    rank: int = 4,
    epochs: float = 3.0,
    learning_rate: float = 5e-5,
    seed: int = 20260809,
) -> dict[str, object]:
    from nightwatch.classifier import CLASSIFIER_PIPELINE_VERSION
    from nightwatch.datasets import load_eval_cases, load_predictions
    from nightwatch.evaluation import evaluate
    from nightwatch.predict_classifier import predict_classifier
    from nightwatch.train_classifier import train_classifier
    from nightwatch.v0 import assess_v0

    if rank not in {4, 8, 16}:
        raise ValueError("rank must be one of 4, 8, or 16")
    validate_gemma_checkpoint(model_id, model_revision)
    if not 1.0 <= epochs <= 6.0:
        raise ValueError("epochs must be between 1 and 6")
    if learning_rate not in {5e-5, 1e-4, 2e-4, 5e-4, 1e-3}:
        raise ValueError("learning_rate is outside the predeclared grid")
    curriculum_bytes = _bounded_payload("curriculum_jsonl", curriculum_jsonl)
    dev_bytes = _bounded_payload("dev_jsonl", dev_jsonl)
    curriculum_sha = hashlib.sha256(curriculum_bytes).hexdigest()
    dev_sha = hashlib.sha256(dev_bytes).hexdigest()
    config = {
        "pipeline_version": CLASSIFIER_PIPELINE_VERSION,
        "model_id": model_id,
        "model_revision": model_revision,
        "rank": rank,
        "epochs": epochs,
        "learning_rate": learning_rate,
        "seed": seed,
    }
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    artifact_name = f"classifier-{curriculum_sha[:8]}-{dev_sha[:8]}-{config_sha[:10]}"
    persistent_adapter = ARTIFACT_ROOT / "adapters" / artifact_name
    persistent_report = ARTIFACT_ROOT / "reports" / f"{artifact_name}.json"
    if persistent_adapter.exists() or persistent_report.exists():
        raise RuntimeError(f"immutable experiment artifact already exists: {artifact_name}")

    work_dir = Path("/tmp/nightwatch-classifier")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    curriculum_path = work_dir / "curriculum.jsonl"
    dev_path = work_dir / "dev.jsonl"
    adapter_path = work_dir / "adapter"
    prediction_path = work_dir / "dev-predictions.jsonl"
    curriculum_path.write_bytes(curriculum_bytes)
    dev_path.write_bytes(dev_bytes)
    manifest = train_classifier(
        curriculum_path,
        dev_path,
        adapter_path,
        rank=rank,
        epochs=epochs,
        learning_rate=learning_rate,
        seed=seed,
        model_id=model_id,
        model_revision=model_revision,
    )
    predict_classifier(
        adapter_path,
        dev_path,
        prediction_path,
        model_id=model_id,
        model_revision=model_revision,
    )
    report = evaluate(
        artifact_name,
        load_eval_cases(dev_path),
        load_predictions(prediction_path),
    )
    result: dict[str, object] = {
        "artifact_name": artifact_name,
        "curriculum_sha256": curriculum_sha,
        "dev_sha256": dev_sha,
        "config": config,
        "training": manifest,
        "dev_evaluation": report.to_dict(),
        "dev_assessment": assess_v0(report).to_dict(),
    }
    persistent_adapter.parent.mkdir(parents=True, exist_ok=True)
    persistent_report.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(adapter_path, persistent_adapter)
    persistent_report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    experiment_artifacts.commit()
    result["predictions_jsonl"] = prediction_path.read_text(encoding="utf-8")
    return result


@app.local_entrypoint()
def classifier_arm(
    curriculum: str = "artifacts/v0-curriculum.jsonl",
    dev: str = "artifacts/v0-dev.jsonl",
    output_dir: str = "artifacts",
    model_id: str = GEMMA_MODEL_ID,
    model_revision: str = GEMMA_MODEL_REVISION,
    rank: int = 4,
    epochs: float = 3.0,
    learning_rate: float = 5e-5,
    seed: int = 20260809,
) -> None:
    result = train_classifier_arm.remote(
        Path(curriculum).read_text(encoding="utf-8"),
        Path(dev).read_text(encoding="utf-8"),
        model_id=model_id,
        model_revision=model_revision,
        rank=rank,
        epochs=epochs,
        learning_rate=learning_rate,
        seed=seed,
    )
    predictions = str(result.pop("predictions_jsonl"))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    artifact_name = str(result["artifact_name"])
    (destination / f"{artifact_name}-dev-predictions.jsonl").write_text(
        predictions,
        encoding="utf-8",
    )
    report_path = destination / f"{artifact_name}-dev-report.json"
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), **result["dev_assessment"]}, indent=2))
