from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import modal

from nightwatch.model_config import GEMMA_MODEL_ID, GEMMA_MODEL_REVISION

APP_NAME = "nightwatch-feasibility"
MAX_INPUT_BYTES = 2_000_000
ARTIFACT_NAME = re.compile(r"^v0-[0-9a-f]{12}-seed-[0-9]+$")
HF_CACHE_ROOT = Path("/cache/huggingface")
ARTIFACT_ROOT = Path("/nightwatch")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "accelerate>=1.12,<2",
        "datasets>=4.4,<5",
        "google-api-core>=2.28,<3",
        "peft>=0.18,<1",
        "torch>=2.9,<3",
        "transformers>=4.57,<5",
        "trl>=0.29,<0.30",
    )
    .env({"HF_HOME": str(HF_CACHE_ROOT), "HF_XET_HIGH_PERFORMANCE": "1"})
    .add_local_python_source("nightwatch")
)

app = modal.App(APP_NAME)
hf_cache = modal.Volume.from_name("nightwatch-hf-cache", create_if_missing=True)
experiment_artifacts = modal.Volume.from_name(
    "nightwatch-experiment-artifacts",
    create_if_missing=True,
)
hf_secret = modal.Secret.from_name(
    "nightwatch-huggingface",
    required_keys=["HF_TOKEN"],
)


@app.function(image=image, secrets=[hf_secret], volumes={str(HF_CACHE_ROOT): hf_cache})
def verify_hf_access() -> dict[str, str]:
    from huggingface_hub import HfApi, model_info

    identity = HfApi().whoami()
    info = model_info(GEMMA_MODEL_ID, revision=GEMMA_MODEL_REVISION)
    return {"account": str(identity["name"]), "model_revision": str(info.sha)}


def _bounded_payload(name: str, value: str) -> bytes:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > MAX_INPUT_BYTES:
        raise ValueError(f"{name} must contain between 1 and {MAX_INPUT_BYTES} UTF-8 bytes")
    return encoded


@app.function(
    image=image,
    gpu="L4",
    timeout=20 * 60,
    secrets=[hf_secret],
    volumes={
        str(HF_CACHE_ROOT): hf_cache,
        str(ARTIFACT_ROOT): experiment_artifacts,
    },
)
def evaluate_saved_v0(
    artifact_name: str,
    eval_jsonl: str,
    *,
    classification_mode: str = "label_logprob",
) -> dict[str, object]:
    from nightwatch.datasets import load_eval_cases, load_predictions
    from nightwatch.evaluation import evaluate
    from nightwatch.predict_gemma import CLASSIFICATION_MODES, predict
    from nightwatch.v0 import assess_v0

    if not ARTIFACT_NAME.fullmatch(artifact_name):
        raise ValueError("artifact_name does not match the immutable v0 format")
    if classification_mode not in CLASSIFICATION_MODES:
        raise ValueError(f"unsupported classification mode: {classification_mode}")
    eval_bytes = _bounded_payload("eval_jsonl", eval_jsonl)
    adapter = ARTIFACT_ROOT / "adapters" / artifact_name
    if not (adapter / "nightwatch-training.json").is_file():
        raise FileNotFoundError(f"completed adapter not found: {artifact_name}")

    work_dir = Path("/tmp/nightwatch-v0-reeval")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    eval_path = work_dir / "eval.jsonl"
    prediction_path = work_dir / "predictions.jsonl"
    eval_path.write_bytes(eval_bytes)
    predict(
        GEMMA_MODEL_ID,
        adapter,
        eval_path,
        prediction_path,
        model_revision=GEMMA_MODEL_REVISION,
        classification_mode=classification_mode,
    )
    report = evaluate(
        f"{artifact_name}:{classification_mode}",
        load_eval_cases(eval_path),
        load_predictions(prediction_path),
    )
    return {
        "artifact_name": artifact_name,
        "classification_mode": classification_mode,
        "evaluation": report.to_dict(),
        "v0_assessment": assess_v0(report).to_dict(),
        "predictions_jsonl": prediction_path.read_text(encoding="utf-8"),
    }


@app.function(
    image=image,
    gpu="L4",
    timeout=60 * 60,
    secrets=[hf_secret],
    volumes={
        str(HF_CACHE_ROOT): hf_cache,
        str(ARTIFACT_ROOT): experiment_artifacts,
    },
)
def train_and_evaluate_v0(
    curriculum_jsonl: str,
    eval_jsonl: str,
    *,
    model_revision: str,
    seed: int = 20260809,
) -> dict[str, object]:
    from nightwatch.datasets import (
        assert_no_eval_leakage,
        dataset_sha256,
        load_curriculum,
        load_eval_cases,
        load_predictions,
    )
    from nightwatch.evaluation import evaluate
    from nightwatch.predict_gemma import predict
    from nightwatch.train_gemma import train
    from nightwatch.v0 import assess_v0, validate_v0_curriculum

    curriculum_bytes = _bounded_payload("curriculum_jsonl", curriculum_jsonl)
    eval_bytes = _bounded_payload("eval_jsonl", eval_jsonl)
    if not model_revision or len(model_revision) > 128:
        raise ValueError("model_revision must be a non-empty immutable revision")

    work_dir = Path("/tmp/nightwatch-v0")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    curriculum_path = work_dir / "curriculum.jsonl"
    eval_path = work_dir / "eval.jsonl"
    prediction_path = work_dir / "predictions.jsonl"
    temporary_adapter = work_dir / "adapter"
    curriculum_path.write_bytes(curriculum_bytes)
    eval_path.write_bytes(eval_bytes)

    raw_rows = [json.loads(line) for line in curriculum_jsonl.splitlines() if line.strip()]
    validated = validate_v0_curriculum(raw_rows, expected_per_label=80)
    cases = load_eval_cases(eval_path)
    assert_no_eval_leakage(validated, cases)

    curriculum_sha = hashlib.sha256(curriculum_bytes).hexdigest()
    eval_sha = hashlib.sha256(eval_bytes).hexdigest()
    artifact_name = f"v0-{curriculum_sha[:12]}-seed-{seed}"
    persistent_adapter = ARTIFACT_ROOT / "adapters" / artifact_name
    persistent_report = ARTIFACT_ROOT / "reports" / f"{artifact_name}.json"
    if persistent_adapter.exists() or persistent_report.exists():
        raise RuntimeError(f"immutable experiment artifact already exists: {artifact_name}")

    started = time.monotonic()
    training_manifest = train(
        GEMMA_MODEL_ID,
        curriculum_path,
        temporary_adapter,
        epochs=8.0,
        learning_rate=2e-4,
        batch_size=4,
        gradient_accumulation_steps=2,
        seed=seed,
        model_revision=model_revision,
    )
    training_seconds = time.monotonic() - started
    prediction_started = time.monotonic()
    predict(
        GEMMA_MODEL_ID,
        temporary_adapter,
        eval_path,
        prediction_path,
        model_revision=model_revision,
    )
    prediction_seconds = time.monotonic() - prediction_started

    report = evaluate(artifact_name, cases, load_predictions(prediction_path))
    assessment = assess_v0(report)
    result: dict[str, object] = {
        "artifact_name": artifact_name,
        "model_id": GEMMA_MODEL_ID,
        "model_revision": model_revision,
        "curriculum_sha256": curriculum_sha,
        "eval_sha256": eval_sha,
        "training_seconds": training_seconds,
        "prediction_seconds": prediction_seconds,
        "training": training_manifest,
        "evaluation": report.to_dict(),
        "v0_assessment": assessment.to_dict(),
    }

    persistent_adapter.parent.mkdir(parents=True, exist_ok=True)
    persistent_report.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(temporary_adapter, persistent_adapter)
    persistent_report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    experiment_artifacts.commit()
    result["predictions_jsonl"] = prediction_path.read_text(encoding="utf-8")
    return result


@app.local_entrypoint()
def main(
    curriculum: str = "artifacts/v0-curriculum.jsonl",
    eval_path: str = "data/eval/frozen.jsonl",
    output_dir: str = "artifacts",
    model_revision: str = GEMMA_MODEL_REVISION,
    seed: int = 20260809,
) -> None:
    curriculum_path = Path(curriculum)
    frozen_path = Path(eval_path)
    result = train_and_evaluate_v0.remote(
        curriculum_path.read_text(encoding="utf-8"),
        frozen_path.read_text(encoding="utf-8"),
        model_revision=model_revision,
        seed=seed,
    )
    predictions = str(result.pop("predictions_jsonl"))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    artifact_name = str(result["artifact_name"])
    (destination / f"{artifact_name}-predictions.jsonl").write_text(
        predictions,
        encoding="utf-8",
    )
    report_path = destination / f"{artifact_name}-report.json"
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), **result["v0_assessment"]}, indent=2))
