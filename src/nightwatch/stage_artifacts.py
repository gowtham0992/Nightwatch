from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from google.api_core.exceptions import Conflict, NotFound, PreconditionFailed

from nightwatch.contracts import Stage
from nightwatch.firestore_journal import validate_cycle_id
from nightwatch.journal import JournalError
from nightwatch.mission_orchestrator import resolve_manifest

GCS_TIMEOUT_SECONDS = 10.0
MAX_STAGE_ARTIFACT_BYTES = 4 * 1024 * 1024


def _canonical_json(value: object) -> bytes:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JournalError("stage artifact must be JSON serializable") from exc
    if not payload or len(payload) > MAX_STAGE_ARTIFACT_BYTES:
        raise JournalError(f"stage artifact exceeds {MAX_STAGE_ARTIFACT_BYTES} bytes")
    return payload


@dataclass(frozen=True)
class StageArtifact:
    cycle_id: str
    stage: Stage
    manifest_id: str
    payload: dict[str, Any]
    sha256: str
    uri: str


def _artifact_from_bytes(raw: bytes, *, uri: str) -> StageArtifact:
    if not raw or len(raw) > MAX_STAGE_ARTIFACT_BYTES:
        raise JournalError("stored stage artifact has an invalid size")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JournalError("stored stage artifact is malformed") from exc
    if not isinstance(value, dict) or set(value) != {
        "cycle_id",
        "manifest_id",
        "payload",
        "stage",
    }:
        raise JournalError("stored stage artifact is malformed")
    try:
        cycle_id = value["cycle_id"]
        stage = Stage(value["stage"])
        manifest_id = value["manifest_id"]
        payload = value["payload"]
        validate_cycle_id(cycle_id)
        resolve_manifest(manifest_id)
        if not isinstance(payload, dict):
            raise JournalError("stored stage artifact payload is malformed")
    except (TypeError, ValueError) as exc:
        if isinstance(exc, JournalError):
            raise
        raise JournalError("stored stage artifact is malformed") from exc
    return StageArtifact(
        cycle_id=cycle_id,
        stage=stage,
        manifest_id=manifest_id,
        payload=payload,
        sha256=hashlib.sha256(raw).hexdigest(),
        uri=uri,
    )


class GCSStageArtifactStore:
    """Create-only stage evidence used to make expensive task retries safe."""

    def __init__(self, bucket: Any) -> None:
        self._bucket = bucket

    @classmethod
    def from_default(
        cls,
        *,
        project: str | None,
        bucket_name: str,
    ) -> GCSStageArtifactStore:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("install the 'cloud' extra to store stage artifacts") from exc
        return cls(storage.Client(project=project).bucket(bucket_name))

    def _identity(
        self,
        cycle_id: str,
        stage: Stage,
        manifest_id: str,
    ) -> tuple[str, str]:
        validate_cycle_id(cycle_id)
        resolve_manifest(manifest_id)
        if stage is Stage.CREATED:
            raise JournalError("created-stage evidence belongs in the mission journal")
        object_name = f"missions/{cycle_id}/stages/{stage.value}.json"
        return object_name, f"gs://{self._bucket.name}/{object_name}"

    def read(
        self,
        cycle_id: str,
        stage: Stage,
        manifest_id: str,
    ) -> StageArtifact | None:
        object_name, uri = self._identity(cycle_id, stage, manifest_id)
        try:
            raw = self._bucket.blob(object_name).download_as_bytes(
                timeout=GCS_TIMEOUT_SECONDS,
            )
        except NotFound:
            return None
        artifact = _artifact_from_bytes(raw, uri=uri)
        if (
            artifact.cycle_id != cycle_id
            or artifact.stage is not stage
            or artifact.manifest_id != manifest_id
        ):
            raise JournalError("stored stage artifact identity does not match its object path")
        return artifact

    def create(
        self,
        cycle_id: str,
        stage: Stage,
        manifest_id: str,
        payload: dict[str, Any],
    ) -> StageArtifact:
        object_name, uri = self._identity(cycle_id, stage, manifest_id)
        raw = _canonical_json(
            {
                "cycle_id": cycle_id,
                "manifest_id": manifest_id,
                "payload": payload,
                "stage": stage.value,
            }
        )
        blob = self._bucket.blob(object_name)
        try:
            blob.upload_from_string(
                raw,
                content_type="application/json",
                if_generation_match=0,
                timeout=GCS_TIMEOUT_SECONDS,
            )
        except (Conflict, PreconditionFailed):
            existing = self.read(cycle_id, stage, manifest_id)
            if existing is None or existing.sha256 != hashlib.sha256(raw).hexdigest():
                raise JournalError("stage artifact already exists with different evidence")
            return existing
        return _artifact_from_bytes(raw, uri=uri)
