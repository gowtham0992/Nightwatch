from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from nightwatch.contracts import Stage
from nightwatch.journal import JournalError
from nightwatch.mission_orchestrator import SAFETY_270M_V1
from nightwatch.modal_training_stage import (
    GCSModalCallStore,
    ModalCallRecord,
    ModalClassifierTrainingStage,
)
from nightwatch.stage_artifacts import StageArtifact


class MemoryArtifacts:
    def __init__(self) -> None:
        self.values: dict[tuple[str, Stage, str], StageArtifact] = {}

    def read(self, cycle_id, stage, manifest_id):
        return self.values.get((cycle_id, stage, manifest_id))

    def create(self, cycle_id, stage, manifest_id, payload):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        artifact = StageArtifact(
            cycle_id=cycle_id,
            stage=stage,
            manifest_id=manifest_id,
            payload=payload,
            sha256=hashlib.sha256(raw).hexdigest(),
            uri=f"gs://private/{cycle_id}/{stage.value}.json",
        )
        existing = self.values.setdefault((cycle_id, stage, manifest_id), artifact)
        if existing != artifact:
            raise JournalError("conflicting stage artifact")
        return existing


class MemoryCalls:
    def __init__(self, *, claimed: bool = False) -> None:
        self.claimed = claimed
        self.record: ModalCallRecord | None = None

    def read_call(self, cycle_id, manifest_id, curriculum_sha256):
        return self.record

    def claim_launch(self, cycle_id, manifest_id, curriculum_sha256):
        if self.claimed:
            return False
        self.claimed = True
        return True

    def record_call(self, record):
        if self.record is not None and self.record != record:
            raise JournalError("different call")
        self.record = record
        return record


class FakeModal:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.spawn_count = 0
        self.get_count = 0
        self.spawned_curriculum = ""

    def spawn_classifier(self, curriculum_jsonl, development_jsonl, *, manifest):
        self.spawn_count += 1
        self.spawned_curriculum = curriculum_jsonl
        assert development_jsonl
        assert manifest == SAFETY_270M_V1
        return "fc-call001"

    def get_result(self, function_call_id, *, timeout_seconds):
        self.get_count += 1
        assert function_call_id == "fc-call001"
        assert timeout_seconds == 1200.0
        return self.result


def seed_curriculum(store: MemoryArtifacts, cycle_id: str) -> tuple[str, str]:
    curriculum = '{"prompt":"generated","label":"page_now"}\n'
    digest = hashlib.sha256(curriculum.encode()).hexdigest()
    store.create(
        cycle_id,
        Stage.CURRICULUM_READY,
        SAFETY_270M_V1.manifest_id,
        {
            "journal_payload": {"curriculum_sha256": digest},
            "curriculum_jsonl": curriculum,
        },
    )
    return curriculum, digest


def modal_result(curriculum_sha: str, development_sha: str) -> dict[str, object]:
    return {
        "artifact_name": "classifier-live-001",
        "curriculum_sha256": curriculum_sha,
        "dev_sha256": development_sha,
        "config": {
            "pipeline_version": 2,
            "model_id": SAFETY_270M_V1.model_id,
            "model_revision": SAFETY_270M_V1.model_revision,
            "rank": SAFETY_270M_V1.lora_rank,
            "epochs": SAFETY_270M_V1.epochs,
            "learning_rate": SAFETY_270M_V1.learning_rate,
            "seed": SAFETY_270M_V1.seed,
        },
        "training": {"train_runtime": 21.5, "examples": 272},
        "dev_evaluation": {"scores": {}},
        "dev_assessment": {"accepted": False},
        "predictions_jsonl": '{"id":"dev-1","label":"investigate"}\n',
    }


def test_training_spawns_once_and_retry_reads_completed_artifact(tmp_path: Path) -> None:
    artifacts = MemoryArtifacts()
    curriculum, curriculum_sha = seed_curriculum(artifacts, "mission-live-201")
    development = '{"id":"dev-1"}\n'
    development_path = tmp_path / "dev.jsonl"
    development_path.write_text(development)
    backend = FakeModal(
        modal_result(curriculum_sha, hashlib.sha256(development.encode()).hexdigest())
    )
    stage = ModalClassifierTrainingStage(
        artifacts,
        MemoryCalls(),
        backend=backend,
        development_evidence_path=development_path,
    )

    first = stage.run("mission-live-201", SAFETY_270M_V1)
    replay = stage.run("mission-live-201", SAFETY_270M_V1)

    assert replay == first
    assert backend.spawn_count == 1
    assert backend.get_count == 1
    assert backend.spawned_curriculum == curriculum
    assert first["attempts"][0]["artifact_name"] == "classifier-live-001"
    assert first["hyperparameter_search"] is False


def test_existing_claim_without_call_id_refuses_duplicate_launch(tmp_path: Path) -> None:
    artifacts = MemoryArtifacts()
    seed_curriculum(artifacts, "mission-live-202")
    development_path = tmp_path / "dev.jsonl"
    development_path.write_text('{"id":"dev-1"}\n')
    backend = FakeModal({})
    stage = ModalClassifierTrainingStage(
        artifacts,
        MemoryCalls(claimed=True),
        backend=backend,
        development_evidence_path=development_path,
    )

    with pytest.raises(JournalError, match="refusing a duplicate"):
        stage.run("mission-live-202", SAFETY_270M_V1)

    assert backend.spawn_count == 0


def test_training_result_must_match_every_manifest_field(tmp_path: Path) -> None:
    artifacts = MemoryArtifacts()
    _, curriculum_sha = seed_curriculum(artifacts, "mission-live-203")
    development = '{"id":"dev-1"}\n'
    development_path = tmp_path / "dev.jsonl"
    development_path.write_text(development)
    result = modal_result(curriculum_sha, hashlib.sha256(development.encode()).hexdigest())
    result["config"] = {**result["config"], "seed": 7}
    stage = ModalClassifierTrainingStage(
        artifacts,
        MemoryCalls(),
        backend=FakeModal(result),
        development_evidence_path=development_path,
    )

    with pytest.raises(JournalError, match="manifest contract"):
        stage.run("mission-live-203", SAFETY_270M_V1)


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket = bucket
        self.name = name

    def download_as_bytes(self, **kwargs):
        assert kwargs == {"timeout": 10.0}
        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        return self.bucket.objects[self.name]

    def upload_from_string(self, payload, **kwargs):
        assert kwargs["if_generation_match"] == 0
        if self.name in self.bucket.objects:
            raise PreconditionFailed("exists")
        self.bucket.objects[self.name] = payload


class FakeBucket:
    name = "private"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def blob(self, name):
        return FakeBlob(self, name)


def test_gcs_launch_claim_and_call_record_are_create_only() -> None:
    bucket = FakeBucket()
    store = GCSModalCallStore(bucket)
    record = ModalCallRecord(
        cycle_id="mission-live-204",
        manifest_id=SAFETY_270M_V1.manifest_id,
        curriculum_sha256="a" * 64,
        function_call_id="fc-call204",
    )

    assert store.claim_launch(record.cycle_id, record.manifest_id, record.curriculum_sha256)
    assert not store.claim_launch(record.cycle_id, record.manifest_id, record.curriculum_sha256)
    assert store.record_call(record) == record
    assert store.record_call(record) == record
    assert store.read_call(
        record.cycle_id, record.manifest_id, record.curriculum_sha256
    ) == record
