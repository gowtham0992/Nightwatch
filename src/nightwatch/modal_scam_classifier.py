from __future__ import annotations

import hashlib
import json
import re
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
from nightwatch.scam_classifier import (
    SCAM_CLASSIFIER_PIPELINE_VERSION,
    SCAM_EVALUATION_BATCH_SIZE,
)


SCAM_ARTIFACT_NAME = re.compile(
    r"^scam-(?:v0|candidate-v[1-8])-[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{10}$"
)


def validate_scam_artifact_name(artifact_name: str) -> str:
    if not SCAM_ARTIFACT_NAME.fullmatch(artifact_name):
        raise ValueError("artifact_name does not match the immutable scam format")
    return artifact_name


def validate_reevaluation_hashes(
    manifest: dict[str, object],
    expected_hashes: dict[str, str],
    *,
    allow_new_evidence: bool,
) -> None:
    if manifest.get("mission_sha256") != expected_hashes["mission_sha256"]:
        raise ValueError("reevaluation mission hash does not match the immutable adapter")
    if (
        not allow_new_evidence
        and manifest.get("development_sha256") != expected_hashes["development_sha256"]
    ):
        raise ValueError("reevaluation inputs do not match the immutable adapter manifest")


@app.function(
    image=image,
    gpu="L4",
    timeout=45 * 60,
    secrets=[hf_secret],
    volumes={
        str(HF_CACHE_ROOT): hf_cache,
        str(ARTIFACT_ROOT): experiment_artifacts,
    },
)
def train_scam_baseline(
    mission_json: str,
    curriculum_jsonl: str,
    development_jsonl: str,
    *,
    rank: int = 8,
    epochs: float = 3.0,
    learning_rate: float = 1e-3,
    seed: int = 20260813,
    experiment_role: str = "baseline",
    selection_metric: str = "macro_f1",
    campaign_id: str | None = None,
) -> dict[str, object]:
    from nightwatch.contracts import Prediction
    from nightwatch.scam_safety import (
        evaluate_scam_safety,
        load_scam_eval_cases,
        load_scam_mission,
    )
    from nightwatch.predict_scam_classifier import predict_scam_classifier
    from nightwatch.train_scam_classifier import train_scam_classifier

    if rank not in {4, 8, 16}:
        raise ValueError("rank must be 4, 8, or 16")
    if not 1.0 <= epochs <= 6.0:
        raise ValueError("epochs must be between 1 and 6")
    if learning_rate not in {1e-4, 2e-4, 5e-4, 1e-3}:
        raise ValueError("learning_rate is outside the predeclared grid")
    if experiment_role not in {
        "baseline",
        "candidate",
        "candidate-v2",
        "candidate-v3",
        "candidate-v4",
        "candidate-v5",
        "candidate-v6",
        "candidate-v7",
        "candidate-v8",
    }:
        raise ValueError(
            "experiment_role must be baseline or candidate-v1 through candidate-v8"
        )
    if selection_metric not in {"macro_f1", "accuracy"}:
        raise ValueError("selection_metric must be macro_f1 or accuracy")
    if campaign_id is not None and not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{2,127}", campaign_id
    ):
        raise ValueError("campaign_id must be a validated Nightwatch cycle identity")
    mission_bytes = _bounded_payload("mission_json", mission_json)
    curriculum_bytes = _bounded_payload("curriculum_jsonl", curriculum_jsonl)
    development_bytes = _bounded_payload("development_jsonl", development_jsonl)
    config = {
        "pipeline_version": SCAM_CLASSIFIER_PIPELINE_VERSION,
        "evaluation_batch_size": SCAM_EVALUATION_BATCH_SIZE,
        "rank": rank,
        "epochs": epochs,
        "learning_rate": learning_rate,
        "seed": seed,
        "experiment_role": experiment_role,
        "selection_metric": selection_metric,
    }
    if campaign_id is not None:
        # Store only a digest in the durable model artifact. The raw cycle ID is
        # orchestration metadata and does not belong in the adapter manifest.
        config["campaign_id_sha256"] = hashlib.sha256(campaign_id.encode()).hexdigest()
    mission_sha = hashlib.sha256(mission_bytes).hexdigest()
    curriculum_sha = hashlib.sha256(curriculum_bytes).hexdigest()
    development_sha = hashlib.sha256(development_bytes).hexdigest()
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    prefix = {
        "baseline": "scam-v0",
        "candidate": "scam-candidate-v1",
        "candidate-v2": "scam-candidate-v2",
        "candidate-v3": "scam-candidate-v3",
        "candidate-v4": "scam-candidate-v4",
        "candidate-v5": "scam-candidate-v5",
        "candidate-v6": "scam-candidate-v6",
        "candidate-v7": "scam-candidate-v7",
        "candidate-v8": "scam-candidate-v8",
    }[experiment_role]
    artifact_name = f"{prefix}-{curriculum_sha[:8]}-{development_sha[:8]}-{config_sha[:10]}"
    persistent_adapter = ARTIFACT_ROOT / "adapters" / artifact_name
    persistent_report = ARTIFACT_ROOT / "reports" / f"{artifact_name}.json"
    if persistent_adapter.exists() or persistent_report.exists():
        raise RuntimeError(f"immutable experiment artifact already exists: {artifact_name}")

    work_dir = Path("/tmp/nightwatch-scam")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    mission_path = work_dir / "mission.json"
    curriculum_path = work_dir / "curriculum.jsonl"
    development_path = work_dir / "development.jsonl"
    adapter_path = work_dir / "adapter"
    predictions_path = work_dir / "development-predictions.jsonl"
    mission_path.write_bytes(mission_bytes)
    curriculum_path.write_bytes(curriculum_bytes)
    development_path.write_bytes(development_bytes)

    mission = load_scam_mission(mission_path)
    training = train_scam_classifier(
        mission_path,
        curriculum_path,
        development_path,
        adapter_path,
        rank=rank,
        epochs=epochs,
        learning_rate=learning_rate,
        seed=seed,
        selection_metric=selection_metric,
    )
    predict_scam_classifier(
        mission_path,
        adapter_path,
        development_path,
        predictions_path,
    )
    prediction_rows = [
        json.loads(line)
        for line in predictions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = evaluate_scam_safety(
        artifact_name,
        load_scam_eval_cases(development_path),
        [Prediction(case_id=row["id"], label=row["label"]) for row in prediction_rows],
    )
    result: dict[str, object] = {
        "artifact_name": artifact_name,
        "mission_id": mission.mission_id,
        "model_id": mission.model_id,
        "model_revision": mission.model_revision,
        "mission_sha256": mission_sha,
        "curriculum_sha256": curriculum_sha,
        "development_sha256": development_sha,
        "config": config,
        "training": training,
        "development_evaluation": report.to_dict(),
    }
    persistent_adapter.parent.mkdir(parents=True, exist_ok=True)
    persistent_report.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(adapter_path, persistent_adapter)
    persistent_report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    experiment_artifacts.commit()
    result["predictions_jsonl"] = predictions_path.read_text(encoding="utf-8")
    return result


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
def evaluate_saved_scam_baseline(
    artifact_name: str,
    mission_json: str,
    development_jsonl: str,
    *,
    batch_size: int = SCAM_EVALUATION_BATCH_SIZE,
    allow_new_evidence: bool = False,
) -> dict[str, object]:
    from nightwatch.contracts import Prediction
    from nightwatch.predict_scam_classifier import predict_scam_classifier
    from nightwatch.scam_safety import evaluate_scam_safety, load_scam_eval_cases

    validate_scam_artifact_name(artifact_name)
    mission_bytes = _bounded_payload("mission_json", mission_json)
    development_bytes = _bounded_payload("development_jsonl", development_jsonl)
    adapter = ARTIFACT_ROOT / "adapters" / artifact_name
    manifest_path = adapter / "nightwatch-scam-training.json"
    report_path = ARTIFACT_ROOT / "reports" / f"{artifact_name}.json"
    if not manifest_path.is_file() or not report_path.is_file():
        raise FileNotFoundError(f"completed adapter not found: {artifact_name}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_hashes = {
        "mission_sha256": hashlib.sha256(mission_bytes).hexdigest(),
        "development_sha256": hashlib.sha256(development_bytes).hexdigest(),
    }
    validate_reevaluation_hashes(
        manifest,
        expected_hashes,
        allow_new_evidence=allow_new_evidence,
    )

    work_dir = Path("/tmp/nightwatch-scam-reeval")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    mission_path = work_dir / "mission.json"
    development_path = work_dir / "development.jsonl"
    predictions_path = work_dir / "development-predictions.jsonl"
    mission_path.write_bytes(mission_bytes)
    development_path.write_bytes(development_bytes)
    predict_scam_classifier(
        mission_path,
        adapter,
        development_path,
        predictions_path,
        batch_size=batch_size,
    )
    prediction_rows = [
        json.loads(line)
        for line in predictions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = evaluate_scam_safety(
        f"{artifact_name}:reevaluation",
        load_scam_eval_cases(development_path),
        [Prediction(case_id=row["id"], label=row["label"]) for row in prediction_rows],
    )
    return {
        "artifact_name": artifact_name,
        "batch_size": batch_size,
        "evidence_relation": "new" if allow_new_evidence else "training-development",
        **expected_hashes,
        "evaluation": report.to_dict(),
        "predictions_jsonl": predictions_path.read_text(encoding="utf-8"),
    }


@app.local_entrypoint()
def scam_baseline(
    mission: str = "data/scam_safety/mission.json",
    curriculum: str = "data/scam_safety/curriculum-v0.jsonl",
    development: str = "data/scam_safety/development-v0.jsonl",
    output_dir: str = "artifacts/scam-safety",
    rank: int = 8,
    epochs: float = 3.0,
    learning_rate: float = 1e-3,
    seed: int = 20260813,
    experiment_role: str = "baseline",
    selection_metric: str = "macro_f1",
    campaign_id: str | None = None,
) -> None:
    result = train_scam_baseline.remote(
        Path(mission).read_text(encoding="utf-8"),
        Path(curriculum).read_text(encoding="utf-8"),
        Path(development).read_text(encoding="utf-8"),
        rank=rank,
        epochs=epochs,
        learning_rate=learning_rate,
        seed=seed,
        experiment_role=experiment_role,
        selection_metric=selection_metric,
        campaign_id=campaign_id,
    )
    predictions = str(result.pop("predictions_jsonl"))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    artifact_name = str(result["artifact_name"])
    (destination / f"{artifact_name}-development-predictions.jsonl").write_text(
        predictions,
        encoding="utf-8",
    )
    report_path = destination / f"{artifact_name}-development-report.json"
    report_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"report": str(report_path), "artifact_name": artifact_name}, indent=2))


@app.local_entrypoint()
def scam_reevaluate(
    artifact_name: str,
    mission: str = "data/scam_safety/mission.json",
    development: str = "data/scam_safety/development-v0.jsonl",
    output_dir: str = "artifacts/scam-safety",
    batch_size: int = SCAM_EVALUATION_BATCH_SIZE,
    allow_new_evidence: bool = False,
) -> None:
    validate_scam_artifact_name(artifact_name)
    result = evaluate_saved_scam_baseline.remote(
        artifact_name,
        Path(mission).read_text(encoding="utf-8"),
        Path(development).read_text(encoding="utf-8"),
        batch_size=batch_size,
        allow_new_evidence=allow_new_evidence,
    )
    predictions = str(result.pop("predictions_jsonl"))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    if allow_new_evidence:
        suffix = f"evidence-{str(result['development_sha256'])[:8]}"
    else:
        suffix = (
            "reevaluation"
            if batch_size == SCAM_EVALUATION_BATCH_SIZE
            else f"reevaluation-batch-{batch_size}"
        )
    predictions_path = destination / f"{artifact_name}-{suffix}-predictions.jsonl"
    report_path = destination / f"{artifact_name}-{suffix}-report.json"
    if predictions_path.exists() or report_path.exists():
        raise RuntimeError(f"immutable local reevaluation already exists: {artifact_name}")
    original_predictions = destination / f"{artifact_name}-development-predictions.jsonl"
    if not allow_new_evidence and original_predictions.is_file():
        original_bytes = original_predictions.read_bytes()
        result["original_predictions_sha256"] = hashlib.sha256(original_bytes).hexdigest()
        result["predictions_match_original"] = original_bytes == predictions.encode("utf-8")
    predictions_path.write_text(predictions, encoding="utf-8")
    result["predictions_sha256"] = hashlib.sha256(predictions.encode("utf-8")).hexdigest()
    report_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"report": str(report_path), "artifact_name": artifact_name}, indent=2))
