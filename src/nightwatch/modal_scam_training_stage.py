from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

from nightwatch.firestore_journal import validate_cycle_id
from nightwatch.journal import JournalError
from nightwatch.mission_orchestrator import MissionManifest
from nightwatch.modal_training_stage import ModalCallRecord, ModalCallStore
from nightwatch.stage_artifacts import StageArtifact


MODAL_APP_NAME = "nightwatch-feasibility"
MODAL_FUNCTION_NAME = "train_scam_baseline"


class ScamModalBackend(Protocol):
    def spawn_classifier(
        self,
        mission_json: str,
        curriculum_jsonl: str,
        development_jsonl: str,
        *,
        cycle_id: str,
        manifest: MissionManifest,
    ) -> str: ...

    def get_result(self, function_call_id: str, *, timeout_seconds: float) -> dict[str, Any]: ...


class ModalScamBackend:
    def __init__(
        self,
        *,
        app_name: str = MODAL_APP_NAME,
        function_name: str = MODAL_FUNCTION_NAME,
    ) -> None:
        self._app_name = app_name
        self._function_name = function_name

    def spawn_classifier(
        self,
        mission_json: str,
        curriculum_jsonl: str,
        development_jsonl: str,
        *,
        cycle_id: str,
        manifest: MissionManifest,
    ) -> str:
        import modal

        validate_cycle_id(cycle_id)
        function = modal.Function.from_name(self._app_name, self._function_name)
        call = function.spawn(
            mission_json,
            curriculum_jsonl,
            development_jsonl,
            rank=manifest.lora_rank,
            epochs=manifest.epochs,
            learning_rate=manifest.learning_rate,
            seed=manifest.seed,
            experiment_role="candidate-v8",
            selection_metric="accuracy",
            campaign_id=cycle_id,
        )
        return call.object_id

    def get_result(self, function_call_id: str, *, timeout_seconds: float) -> dict[str, Any]:
        import modal

        result = modal.FunctionCall.from_id(function_call_id).get(timeout=timeout_seconds)
        if not isinstance(result, dict):
            raise JournalError("Modal scam training returned a non-object result")
        return result


class ModalScamTrainingCampaign:
    """One approved paid repair attempt with durable launch identity.

    The broader controller supports a bounded campaign, but this implementation
    deliberately launches one known intervention. A rejected gate remains a
    valid terminal result; it never triggers an unrecorded parameter search.
    """

    def __init__(
        self,
        call_store: ModalCallStore,
        *,
        backend: ScamModalBackend | None = None,
        mission_path: Path = Path("data/scam_safety/mission.json"),
        baseline_predictions_path: Path = Path(
            "artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-evidence-ffca8c22-predictions.jsonl"
        ),
    ) -> None:
        self._calls = call_store
        self._backend = backend or ModalScamBackend()
        self._mission_path = mission_path
        self._baseline_predictions_path = baseline_predictions_path

    def run(
        self,
        cycle_id: str,
        manifest: MissionManifest,
        curriculum_artifact: StageArtifact,
    ) -> dict[str, Any]:
        validate_cycle_id(cycle_id)
        curriculum_jsonl = curriculum_artifact.payload.get("curriculum_jsonl")
        development_jsonl = curriculum_artifact.payload.get("development_jsonl")
        projection = curriculum_artifact.payload.get("journal_payload")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (curriculum_jsonl, development_jsonl)
        ) or not isinstance(projection, dict):
            raise JournalError("scam curriculum artifact is not trainable")
        curriculum_sha = hashlib.sha256(curriculum_jsonl.encode()).hexdigest()
        development_sha = hashlib.sha256(development_jsonl.encode()).hexdigest()
        if (
            projection.get("curriculum_sha256") != curriculum_sha
            or projection.get("development_sha256") != development_sha
        ):
            raise JournalError("scam curriculum artifact identity is inconsistent")

        mission_json = self._mission_path.read_text(encoding="utf-8")
        mission_sha = hashlib.sha256(mission_json.encode()).hexdigest()
        call = self._calls.read_call(cycle_id, manifest.manifest_id, curriculum_sha)
        if call is None:
            if not self._calls.claim_launch(cycle_id, manifest.manifest_id, curriculum_sha):
                call = self._calls.read_call(cycle_id, manifest.manifest_id, curriculum_sha)
                if call is None:
                    raise JournalError(
                        "Modal scam launch is claimed without a call record; refusing duplicate spend"
                    )
            else:
                call_id = self._backend.spawn_classifier(
                    mission_json,
                    curriculum_jsonl,
                    development_jsonl,
                    cycle_id=cycle_id,
                    manifest=manifest,
                )
                call = self._calls.record_call(
                    ModalCallRecord(
                        cycle_id=cycle_id,
                        manifest_id=manifest.manifest_id,
                        curriculum_sha256=curriculum_sha,
                        function_call_id=call_id,
                    )
                )

        result = self._backend.get_result(
            call.function_call_id,
            timeout_seconds=float(manifest.maximum_gpu_minutes * 60),
        )
        config = result.get("config")
        artifact_name = result.get("artifact_name")
        predictions_jsonl = result.get("predictions_jsonl")
        training = result.get("training")
        expected_campaign_digest = hashlib.sha256(cycle_id.encode()).hexdigest()
        if (
            result.get("mission_id") != "scam-safety-v1"
            or result.get("model_id") != manifest.model_id
            or result.get("model_revision") != manifest.model_revision
            or result.get("mission_sha256") != mission_sha
            or result.get("curriculum_sha256") != curriculum_sha
            or result.get("development_sha256") != development_sha
            or not isinstance(config, dict)
            or config.get("pipeline_version") != 3
            or config.get("rank") != manifest.lora_rank
            or config.get("epochs") != manifest.epochs
            or config.get("learning_rate") != manifest.learning_rate
            or config.get("seed") != manifest.seed
            or config.get("experiment_role") != "candidate-v8"
            or config.get("selection_metric") != "accuracy"
            or config.get("campaign_id_sha256") != expected_campaign_digest
            or not isinstance(artifact_name, str)
            or not artifact_name.startswith("scam-candidate-v8-")
            or not isinstance(predictions_jsonl, str)
            or not predictions_jsonl.strip()
            or not isinstance(training, dict)
        ):
            raise JournalError("Modal scam result failed the approved campaign contract")

        baseline_predictions = self._baseline_predictions_path.read_text(encoding="utf-8")
        if not baseline_predictions.strip():
            raise JournalError("baseline prediction evidence is empty")
        return {
            "attempts": [
                {
                    "attempt": 1,
                    "artifact_name": artifact_name,
                    "runtime_seconds": training.get("train_runtime"),
                    "examples": training.get("examples"),
                    "seed": manifest.seed,
                    "modal_call_id": call.function_call_id,
                }
            ],
            "baseline_predictions_jsonl": baseline_predictions,
            "candidate": {
                "artifact_name": artifact_name,
                "predictions_jsonl": predictions_jsonl,
                "training": training,
            },
        }
