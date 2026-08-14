from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nightwatch.contracts import Stage
from nightwatch.journal import JournalError
from nightwatch.mission_orchestrator import SCAM_SAFETY_1B_V1
from nightwatch.modal_scam_training_stage import ModalScamTrainingCampaign
from nightwatch.modal_training_stage import ModalCallRecord
from nightwatch.stage_artifacts import StageArtifact


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
        self.record = record
        return record


class FakeModal:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.spawns = 0
        self.gets = 0

    def spawn_classifier(
        self,
        mission_json,
        curriculum_jsonl,
        development_jsonl,
        *,
        cycle_id,
        manifest,
    ):
        self.spawns += 1
        assert mission_json and curriculum_jsonl and development_jsonl
        assert cycle_id == "mission-scam-modal-001"
        assert manifest == SCAM_SAFETY_1B_V1
        return "fc-scam001"

    def get_result(self, function_call_id, *, timeout_seconds):
        self.gets += 1
        assert function_call_id == "fc-scam001"
        assert timeout_seconds == 1200.0
        return self.result


def _curriculum() -> StageArtifact:
    curriculum = Path("data/scam_safety/curriculum-v5.jsonl").read_text()
    development = Path("data/scam_safety/development-v1.jsonl").read_text()
    return StageArtifact(
        cycle_id="mission-scam-modal-001",
        stage=Stage.CURRICULUM_READY,
        manifest_id=SCAM_SAFETY_1B_V1.manifest_id,
        payload={
            "journal_payload": {
                "curriculum_sha256": hashlib.sha256(curriculum.encode()).hexdigest(),
                "development_sha256": hashlib.sha256(development.encode()).hexdigest(),
            },
            "curriculum_jsonl": curriculum,
            "development_jsonl": development,
        },
        sha256="a" * 64,
        uri="gs://private/curriculum.json",
    )


def _result(cycle_id: str) -> dict[str, object]:
    artifact = _curriculum()
    mission = Path("data/scam_safety/mission.json").read_text()
    curriculum = artifact.payload["curriculum_jsonl"]
    development = artifact.payload["development_jsonl"]
    return {
        "artifact_name": "scam-candidate-v8-fd2b06dd-ffca8c22-1234567890",
        "mission_id": "scam-safety-v1",
        "model_id": SCAM_SAFETY_1B_V1.model_id,
        "model_revision": SCAM_SAFETY_1B_V1.model_revision,
        "mission_sha256": hashlib.sha256(mission.encode()).hexdigest(),
        "curriculum_sha256": hashlib.sha256(curriculum.encode()).hexdigest(),
        "development_sha256": hashlib.sha256(development.encode()).hexdigest(),
        "config": {
            "pipeline_version": 3,
            "evaluation_batch_size": 1,
            "rank": SCAM_SAFETY_1B_V1.lora_rank,
            "epochs": SCAM_SAFETY_1B_V1.epochs,
            "learning_rate": SCAM_SAFETY_1B_V1.learning_rate,
            "seed": SCAM_SAFETY_1B_V1.seed,
            "experiment_role": "candidate-v8",
            "selection_metric": "accuracy",
            "campaign_id_sha256": hashlib.sha256(cycle_id.encode()).hexdigest(),
        },
        "training": {"train_runtime": 46.0, "examples": 416},
        "predictions_jsonl": '{"id":"target-001","label":"block","confidence":0.9}\n',
    }


def test_campaign_claims_one_modal_launch_and_returns_gate_inputs() -> None:
    backend = FakeModal(_result("mission-scam-modal-001"))
    calls = MemoryCalls()
    campaign = ModalScamTrainingCampaign(calls, backend=backend)

    result = campaign.run(
        "mission-scam-modal-001", SCAM_SAFETY_1B_V1, _curriculum()
    )

    assert backend.spawns == 1
    assert backend.gets == 1
    assert calls.record is not None
    assert result["attempts"][0]["modal_call_id"] == "fc-scam001"
    assert result["candidate"]["artifact_name"].startswith("scam-candidate-v8-")
    assert result["baseline_predictions_jsonl"].strip()


def test_existing_claim_without_call_id_refuses_duplicate_gpu_spend() -> None:
    backend = FakeModal({})
    campaign = ModalScamTrainingCampaign(MemoryCalls(claimed=True), backend=backend)

    with pytest.raises(JournalError, match="refusing duplicate spend"):
        campaign.run("mission-scam-modal-001", SCAM_SAFETY_1B_V1, _curriculum())

    assert backend.spawns == 0


def test_modal_result_must_bind_to_cycle_and_manifest() -> None:
    result = _result("mission-scam-modal-001")
    result["config"] = {**result["config"], "campaign_id_sha256": "0" * 64}
    campaign = ModalScamTrainingCampaign(
        MemoryCalls(), backend=FakeModal(result)
    )

    with pytest.raises(JournalError, match="campaign contract"):
        campaign.run("mission-scam-modal-001", SCAM_SAFETY_1B_V1, _curriculum())
