from __future__ import annotations

import json

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from nightwatch.contracts import Stage
from nightwatch.journal import JournalError
from nightwatch.mission_orchestrator import SAFETY_270M_V1
from nightwatch.stage_artifacts import GCSStageArtifactStore


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket = bucket
        self.name = name
        self.upload_options: dict[str, object] | None = None

    def download_as_bytes(self, **kwargs: object) -> bytes:
        assert kwargs == {"timeout": 10.0}
        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        return self.bucket.objects[self.name]

    def upload_from_string(self, payload: bytes, **kwargs: object) -> None:
        self.upload_options = kwargs
        if self.name in self.bucket.objects:
            raise PreconditionFailed("already exists")
        self.bucket.objects[self.name] = payload


class FakeBucket:
    name = "nightwatch-stage-artifacts"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.blobs: list[FakeBlob] = []

    def blob(self, name: str) -> FakeBlob:
        blob = FakeBlob(self, name)
        self.blobs.append(blob)
        return blob


def test_create_only_stage_artifact_round_trips_with_content_identity() -> None:
    bucket = FakeBucket()
    store = GCSStageArtifactStore(bucket)

    artifact = store.create(
        "mission-live-001",
        Stage.DIAGNOSED,
        SAFETY_270M_V1.manifest_id,
        {"finding": "safety floor missed", "accuracy": 0.8333},
    )
    loaded = store.read(
        "mission-live-001",
        Stage.DIAGNOSED,
        SAFETY_270M_V1.manifest_id,
    )

    assert loaded == artifact
    assert artifact.uri == (
        "gs://nightwatch-stage-artifacts/missions/mission-live-001/"
        "stages/diagnosed.json"
    )
    assert len(artifact.sha256) == 64
    assert bucket.blobs[0].upload_options == {
        "content_type": "application/json",
        "if_generation_match": 0,
        "timeout": 10.0,
    }


def test_identical_create_retry_returns_existing_artifact() -> None:
    store = GCSStageArtifactStore(FakeBucket())
    first = store.create(
        "mission-live-002",
        Stage.TRAINED,
        SAFETY_270M_V1.manifest_id,
        {"modal_call_id": "fc-123"},
    )

    replay = store.create(
        "mission-live-002",
        Stage.TRAINED,
        SAFETY_270M_V1.manifest_id,
        {"modal_call_id": "fc-123"},
    )

    assert replay == first


def test_conflicting_retry_fails_closed() -> None:
    store = GCSStageArtifactStore(FakeBucket())
    store.create(
        "mission-live-003",
        Stage.TRAINED,
        SAFETY_270M_V1.manifest_id,
        {"modal_call_id": "fc-original"},
    )

    with pytest.raises(JournalError, match="different evidence"):
        store.create(
            "mission-live-003",
            Stage.TRAINED,
            SAFETY_270M_V1.manifest_id,
            {"modal_call_id": "fc-attacker"},
        )


def test_path_content_identity_mismatch_is_rejected() -> None:
    bucket = FakeBucket()
    object_name = "missions/mission-live-004/stages/diagnosed.json"
    bucket.objects[object_name] = json.dumps(
        {
            "cycle_id": "different-cycle",
            "manifest_id": SAFETY_270M_V1.manifest_id,
            "payload": {},
            "stage": "diagnosed",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    store = GCSStageArtifactStore(bucket)

    with pytest.raises(JournalError, match="object path"):
        store.read(
            "mission-live-004",
            Stage.DIAGNOSED,
            SAFETY_270M_V1.manifest_id,
        )


@pytest.mark.parametrize(
    ("cycle_id", "stage", "manifest_id"),
    [
        ("../escape", Stage.DIAGNOSED, SAFETY_270M_V1.manifest_id),
        ("mission-live-005", Stage.CREATED, SAFETY_270M_V1.manifest_id),
        ("mission-live-005", Stage.DIAGNOSED, "unapproved"),
    ],
)
def test_untrusted_artifact_identity_is_rejected(cycle_id, stage, manifest_id) -> None:
    store = GCSStageArtifactStore(FakeBucket())

    with pytest.raises(JournalError):
        store.read(cycle_id, stage, manifest_id)


def test_specialist_artifacts_are_independently_sealed_and_retry_safe() -> None:
    store = GCSStageArtifactStore(FakeBucket())
    payload = {
        "specialist": "target_repair",
        "assignment": "Repair observed target failures.",
        "rationale": "Add bounded contrasts around the observed error family.",
        "examples": [{"text": "Example message", "label": "block"}] * 8,
    }

    first = store.create_specialist(
        "mission-live-006", Stage.CURRICULUM_READY, SAFETY_270M_V1.manifest_id,
        "target_repair", payload,
    )
    replay = store.create_specialist(
        "mission-live-006", Stage.CURRICULUM_READY, SAFETY_270M_V1.manifest_id,
        "target_repair", payload,
    )

    assert replay == first
    assert first.uri.endswith("/curriculum_ready/specialists/target_repair.json")
    assert store.read_specialist(
        "mission-live-006", Stage.CURRICULUM_READY, SAFETY_270M_V1.manifest_id,
        "target_repair",
    ) == first


def test_specialist_artifact_rejects_path_or_payload_identity_changes() -> None:
    store = GCSStageArtifactStore(FakeBucket())

    with pytest.raises(JournalError, match="payload identity"):
        store.create_specialist(
            "mission-live-007", Stage.CURRICULUM_READY, SAFETY_270M_V1.manifest_id,
            "target_repair", {"specialist": "regression_guard"},
        )

    with pytest.raises(JournalError, match="identity"):
        store.read_specialist(
            "mission-live-007", Stage.TRAINED, SAFETY_270M_V1.manifest_id,
            "../escape",
        )
