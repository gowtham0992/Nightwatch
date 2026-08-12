from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from google.api_core.exceptions import Conflict, NotFound, PreconditionFailed

from nightwatch.contracts import Stage
from nightwatch.firestore_journal import validate_cycle_id
from nightwatch.journal import JournalError
from nightwatch.mission_orchestrator import MissionManifest, resolve_manifest
from nightwatch.stage_artifacts import GCS_TIMEOUT_SECONDS, StageArtifact

MODAL_APP_NAME = "nightwatch-feasibility"
MODAL_FUNCTION_NAME = "train_classifier_arm"
MAX_CALL_RECORD_BYTES = 16 * 1024
_FUNCTION_CALL_ID = re.compile(r"^fc-[A-Za-z0-9_-]{4,200}$")


class TrainingArtifactStore(Protocol):
    def read(self, cycle_id: str, stage: Stage, manifest_id: str) -> StageArtifact | None: ...

    def create(
        self,
        cycle_id: str,
        stage: Stage,
        manifest_id: str,
        payload: dict[str, Any],
    ) -> StageArtifact: ...


@dataclass(frozen=True)
class ModalCallRecord:
    cycle_id: str
    manifest_id: str
    curriculum_sha256: str
    function_call_id: str


class ModalCallStore(Protocol):
    def read_call(
        self, cycle_id: str, manifest_id: str, curriculum_sha256: str
    ) -> ModalCallRecord | None: ...

    def claim_launch(self, cycle_id: str, manifest_id: str, curriculum_sha256: str) -> bool: ...

    def record_call(self, record: ModalCallRecord) -> ModalCallRecord: ...


class ModalBackend(Protocol):
    def spawn_classifier(
        self,
        curriculum_jsonl: str,
        development_jsonl: str,
        *,
        manifest: MissionManifest,
    ) -> str: ...

    def get_result(self, function_call_id: str, *, timeout_seconds: float) -> dict[str, Any]: ...


def _validate_digest(value: str, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise JournalError(f"{label} must be a lowercase SHA-256 digest")


def _call_record_from_bytes(raw: bytes) -> ModalCallRecord:
    if not raw or len(raw) > MAX_CALL_RECORD_BYTES:
        raise JournalError("Modal call record has an invalid size")
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {
            "curriculum_sha256",
            "cycle_id",
            "function_call_id",
            "manifest_id",
        }:
            raise JournalError("Modal call record is malformed")
        record = ModalCallRecord(**value)
        validate_cycle_id(record.cycle_id)
        resolve_manifest(record.manifest_id)
        _validate_digest(record.curriculum_sha256, "curriculum identity")
        if not _FUNCTION_CALL_ID.fullmatch(record.function_call_id):
            raise JournalError("Modal function call ID is malformed")
        return record
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
        if isinstance(exc, JournalError):
            raise
        raise JournalError("Modal call record is malformed") from exc


class GCSModalCallStore:
    """Create a launch claim before spawning and persist the call ID afterward.

    A crash between those writes leaves an ambiguous claim and fails closed;
    Nightwatch will not pay for a second launch merely to recover.
    """

    def __init__(self, bucket: Any) -> None:
        self._bucket = bucket

    @classmethod
    def from_default(cls, *, project: str | None, bucket_name: str) -> GCSModalCallStore:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("install the 'cloud' extra to store Modal call identity") from exc
        return cls(storage.Client(project=project).bucket(bucket_name))

    @staticmethod
    def _validate_identity(cycle_id: str, manifest_id: str, curriculum_sha256: str) -> None:
        validate_cycle_id(cycle_id)
        resolve_manifest(manifest_id)
        _validate_digest(curriculum_sha256, "curriculum identity")

    @staticmethod
    def _claim_name(cycle_id: str) -> str:
        return f"missions/{cycle_id}/operations/modal-training-claim.json"

    @staticmethod
    def _call_name(cycle_id: str) -> str:
        return f"missions/{cycle_id}/operations/modal-training-call.json"

    def read_call(
        self, cycle_id: str, manifest_id: str, curriculum_sha256: str
    ) -> ModalCallRecord | None:
        self._validate_identity(cycle_id, manifest_id, curriculum_sha256)
        try:
            raw = self._bucket.blob(self._call_name(cycle_id)).download_as_bytes(
                timeout=GCS_TIMEOUT_SECONDS
            )
        except NotFound:
            return None
        record = _call_record_from_bytes(raw)
        if (
            record.cycle_id != cycle_id
            or record.manifest_id != manifest_id
            or record.curriculum_sha256 != curriculum_sha256
        ):
            raise JournalError("Modal call identity does not match its object path")
        return record

    def claim_launch(self, cycle_id: str, manifest_id: str, curriculum_sha256: str) -> bool:
        self._validate_identity(cycle_id, manifest_id, curriculum_sha256)
        raw = json.dumps(
            {
                "curriculum_sha256": curriculum_sha256,
                "cycle_id": cycle_id,
                "manifest_id": manifest_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        try:
            self._bucket.blob(self._claim_name(cycle_id)).upload_from_string(
                raw,
                content_type="application/json",
                if_generation_match=0,
                timeout=GCS_TIMEOUT_SECONDS,
            )
        except (Conflict, PreconditionFailed):
            return False
        return True

    def record_call(self, record: ModalCallRecord) -> ModalCallRecord:
        self._validate_identity(record.cycle_id, record.manifest_id, record.curriculum_sha256)
        if not _FUNCTION_CALL_ID.fullmatch(record.function_call_id):
            raise JournalError("Modal function call ID is malformed")
        raw = json.dumps(record.__dict__, sort_keys=True, separators=(",", ":")).encode()
        blob = self._bucket.blob(self._call_name(record.cycle_id))
        try:
            blob.upload_from_string(
                raw,
                content_type="application/json",
                if_generation_match=0,
                timeout=GCS_TIMEOUT_SECONDS,
            )
        except (Conflict, PreconditionFailed):
            existing = self.read_call(
                record.cycle_id, record.manifest_id, record.curriculum_sha256
            )
            if existing != record:
                raise JournalError("Modal call record already exists with different identity")
            return existing
        return record


class ModalSDKBackend:
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
        curriculum_jsonl: str,
        development_jsonl: str,
        *,
        manifest: MissionManifest,
    ) -> str:
        import modal

        function = modal.Function.from_name(self._app_name, self._function_name)
        call = function.spawn(
            curriculum_jsonl,
            development_jsonl,
            model_id=manifest.model_id,
            model_revision=manifest.model_revision,
            rank=manifest.lora_rank,
            epochs=manifest.epochs,
            learning_rate=manifest.learning_rate,
            seed=manifest.seed,
        )
        return call.object_id

    def get_result(self, function_call_id: str, *, timeout_seconds: float) -> dict[str, Any]:
        import modal

        result = modal.FunctionCall.from_id(function_call_id).get(timeout=timeout_seconds)
        if not isinstance(result, dict):
            raise JournalError("Modal training returned a non-object result")
        return result


class ModalClassifierTrainingStage:
    def __init__(
        self,
        artifact_store: TrainingArtifactStore,
        call_store: ModalCallStore,
        *,
        backend: ModalBackend | None = None,
        development_evidence_path: Path = Path("artifacts/v0-dev.jsonl"),
    ) -> None:
        self._artifacts = artifact_store
        self._calls = call_store
        self._backend = backend or ModalSDKBackend()
        self._development_evidence_path = development_evidence_path

    @staticmethod
    def _journal_payload(artifact: StageArtifact) -> dict[str, Any]:
        projection = artifact.payload.get("journal_payload")
        if not isinstance(projection, dict):
            raise JournalError("training artifact is missing its journal projection")
        return {
            "manifest_id": artifact.manifest_id,
            "artifact_uri": artifact.uri,
            "artifact_sha256": artifact.sha256,
            **projection,
        }

    def run(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        complete = self._artifacts.read(cycle_id, Stage.TRAINED, manifest.manifest_id)
        if complete is not None:
            return self._journal_payload(complete)

        curriculum = self._artifacts.read(
            cycle_id, Stage.CURRICULUM_READY, manifest.manifest_id
        )
        if curriculum is None:
            raise JournalError("training cannot start before immutable curriculum evidence exists")
        curriculum_jsonl = curriculum.payload.get("curriculum_jsonl")
        if not isinstance(curriculum_jsonl, str) or not curriculum_jsonl.strip():
            raise JournalError("curriculum artifact does not contain trainable JSONL")
        curriculum_sha256 = hashlib.sha256(curriculum_jsonl.encode()).hexdigest()
        curriculum_projection = curriculum.payload.get("journal_payload")
        if (
            not isinstance(curriculum_projection, dict)
            or curriculum_projection.get("curriculum_sha256") != curriculum_sha256
        ):
            raise JournalError("curriculum artifact identity is inconsistent")

        development_jsonl = self._development_evidence_path.read_text(encoding="utf-8")
        development_sha256 = hashlib.sha256(development_jsonl.encode()).hexdigest()
        call = self._calls.read_call(cycle_id, manifest.manifest_id, curriculum_sha256)
        if call is None:
            if not self._calls.claim_launch(cycle_id, manifest.manifest_id, curriculum_sha256):
                call = self._calls.read_call(cycle_id, manifest.manifest_id, curriculum_sha256)
                if call is None:
                    raise JournalError(
                        "Modal launch is claimed without a call record; refusing a duplicate launch"
                    )
            else:
                call_id = self._backend.spawn_classifier(
                    curriculum_jsonl, development_jsonl, manifest=manifest
                )
                call = self._calls.record_call(
                    ModalCallRecord(
                        cycle_id=cycle_id,
                        manifest_id=manifest.manifest_id,
                        curriculum_sha256=curriculum_sha256,
                        function_call_id=call_id,
                    )
                )

        result = self._backend.get_result(
            call.function_call_id,
            timeout_seconds=float(manifest.maximum_gpu_minutes * 60),
        )
        try:
            config = result["config"]
            training = result["training"]
            artifact_name = result["artifact_name"]
            predictions_jsonl = result["predictions_jsonl"]
        except KeyError as exc:
            raise JournalError("Modal training result is missing required evidence") from exc
        expected_config = {
            "pipeline_version": 2,
            "model_id": manifest.model_id,
            "model_revision": manifest.model_revision,
            "rank": manifest.lora_rank,
            "epochs": manifest.epochs,
            "learning_rate": manifest.learning_rate,
            "seed": manifest.seed,
        }
        if (
            config != expected_config
            or result.get("curriculum_sha256") != curriculum_sha256
            or result.get("dev_sha256") != development_sha256
            or not isinstance(training, dict)
            or not isinstance(artifact_name, str)
            or not artifact_name.startswith("classifier-")
            or not isinstance(predictions_jsonl, str)
            or not predictions_jsonl.strip()
        ):
            raise JournalError("Modal training result failed the approved manifest contract")

        journal_projection = {
            "executor": "modal",
            "attempts": [
                {
                    "artifact_name": artifact_name,
                    "model_id": manifest.model_id,
                    "model_revision": manifest.model_revision,
                    "training_runtime_seconds": training.get("train_runtime"),
                    "examples": training.get("examples"),
                    "seed": manifest.seed,
                }
            ],
            "selection_policy": "one pinned 270M intervention",
            "hyperparameter_search": False,
            "modal_call_id": call.function_call_id,
        }
        artifact = self._artifacts.create(
            cycle_id,
            Stage.TRAINED,
            manifest.manifest_id,
            {"journal_payload": journal_projection, "modal_result": result},
        )
        return self._journal_payload(artifact)
