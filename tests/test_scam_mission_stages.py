from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nightwatch.contracts import Stage
from nightwatch.journal import JournalError, append_stage, read_journal
from nightwatch.mission_orchestrator import SCAM_SAFETY_1B_V1, advance_mission
from nightwatch.scam_mission_stages import (
    ManifestStageExecutor,
    ScamSafetyStageExecutor,
    retained_verified_curriculum,
    retained_verified_diagnosis,
)
from nightwatch.scam_repair_agent import build_scam_failure_packet
from nightwatch.stage_artifacts import StageArtifact


BASELINE = "scam-v0-de1e6009-2d77e636-c0e947096d"
CANDIDATE = "scam-candidate-v8-fd2b06dd-ffca8c22-7e228df886"


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
            raise JournalError("conflicting artifact")
        return existing


class FileJournal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read_cycle(self, cycle_id):
        return [entry for entry in read_journal(self.path) if entry.cycle_id == cycle_id]

    def append_stage(self, cycle_id, stage, payload, *, timestamp=None):
        return append_stage(self.path, cycle_id, stage, payload, timestamp=timestamp)


def _retained_plan(_packet: dict[str, object]) -> dict[str, object]:
    return json.loads(
        Path(f"artifacts/scam-safety/{BASELINE}-repair-plan.json").read_text()
    )["plan"]


def _retained_curriculum(_diagnosis: dict[str, object]) -> dict[str, object]:
    return {
        "curriculum_jsonl": Path("data/scam_safety/curriculum-v5.jsonl").read_text(),
        "development_jsonl": Path("data/scam_safety/development-v1.jsonl").read_text(),
        "authoring_evidence": json.loads(
            Path("artifacts/scam-safety/repair-authoring-v5.json").read_text()
        ),
    }


class RetainedCampaign:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, cycle_id, manifest, curriculum_artifact):
        self.calls += 1
        assert cycle_id == "mission-scam-001"
        assert manifest == SCAM_SAFETY_1B_V1
        assert curriculum_artifact.stage is Stage.CURRICULUM_READY
        candidate_report = json.loads(
            Path(f"artifacts/scam-safety/{CANDIDATE}-development-report.json").read_text()
        )
        return {
            "attempts": [
                {
                    "attempt": 8,
                    "artifact_name": CANDIDATE,
                    "runtime_seconds": candidate_report["training"]["train_runtime"],
                    "selection_metric": candidate_report["config"]["selection_metric"],
                }
            ],
            "baseline_predictions_jsonl": Path(
                f"artifacts/scam-safety/{BASELINE}-evidence-ffca8c22-predictions.jsonl"
            ).read_text(),
            "candidate": {
                "artifact_name": CANDIDATE,
                "predictions_jsonl": Path(
                    f"artifacts/scam-safety/{CANDIDATE}-development-predictions.jsonl"
                ).read_text(),
                "training": candidate_report["training"],
            },
        }


def _executor(artifacts: MemoryArtifacts, campaign: RetainedCampaign | None = None):
    return ScamSafetyStageExecutor(
        artifacts,
        diagnostician=_retained_plan,
        curriculum_architect=_retained_curriculum,
        training_campaign=campaign,
    )


def test_scam_manifest_records_specific_trigger_and_never_authorizes_deployment(
    tmp_path: Path,
) -> None:
    journal = FileJournal(tmp_path / "mission.jsonl")

    result = advance_mission(
        "mission-scam-created",
        SCAM_SAFETY_1B_V1.manifest_id,
        journal=journal,
        executor=_executor(MemoryArtifacts()),
    )

    entry = journal.read_cycle("mission-scam-created")[0]
    assert result.stage is Stage.CREATED
    assert entry.payload["mission_kind"] == "bounded_scam_safety_repair"
    assert entry.payload["trigger"]["artifact_name"] == BASELINE
    assert entry.payload["trigger"]["minimum_target_gain"] == 0.15
    assert entry.payload["deployment_authorized"] is False
    assert entry.payload["limits"]["maximum_training_attempts"] == 8


def test_real_scam_evidence_advances_to_deterministic_qualification(tmp_path: Path) -> None:
    artifacts = MemoryArtifacts()
    campaign = RetainedCampaign()
    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = _executor(artifacts, campaign)

    results = [
        advance_mission(
            "mission-scam-001",
            SCAM_SAFETY_1B_V1.manifest_id,
            journal=journal,
            executor=executor,
        )
        for _ in range(6)
    ]

    assert [result.stage for result in results] == [
        Stage.CREATED,
        Stage.DIAGNOSED,
        Stage.CURRICULUM_READY,
        Stage.TRAINED,
        Stage.EVALUATED,
        Stage.PROMOTED,
    ]
    entries = journal.read_cycle("mission-scam-001")
    assert entries[1].payload["actor"] == "gemini_adk_diagnostician"
    assert entries[2].payload["leakage_check"] == "passed"
    assert entries[3].payload["selected_artifact"] == CANDIDATE
    assert entries[4].payload["accepted"] is True
    assert entries[4].payload["candidate"]["scores"] == {
        "target": {"correct": 36, "total": 36, "accuracy": 1.0},
        "regression": {"correct": 28, "total": 32, "accuracy": 0.875},
        "safety": {"correct": 24, "total": 24, "accuracy": 1.0},
    }
    assert entries[5].payload["deployment_status"] == "qualified_not_deployed"
    assert entries[5].payload["promotion_authority"] == "deterministic_code_only"
    assert campaign.calls == 1


def test_retry_reads_stage_artifact_without_repeating_training(tmp_path: Path) -> None:
    artifacts = MemoryArtifacts()
    campaign = RetainedCampaign()
    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = _executor(artifacts, campaign)
    for _ in range(4):
        advance_mission(
            "mission-scam-001",
            SCAM_SAFETY_1B_V1.manifest_id,
            journal=journal,
            executor=executor,
        )

    trained = executor.execute(
        "mission-scam-001",
        Stage.TRAINED,
        SCAM_SAFETY_1B_V1,
        tuple(journal.read_cycle("mission-scam-001")),
    )

    assert trained["selected_artifact"] == CANDIDATE
    assert campaign.calls == 1


def test_training_refuses_to_run_without_a_bounded_campaign() -> None:
    artifacts = MemoryArtifacts()
    artifacts.create(
        "mission-scam-unwired",
        Stage.CURRICULUM_READY,
        SCAM_SAFETY_1B_V1.manifest_id,
        {
            "journal_payload": {},
            "curriculum_jsonl": "{}\n",
            "development_jsonl": "{}\n",
        },
    )

    with pytest.raises(JournalError, match="not configured"):
        _executor(artifacts).execute(
            "mission-scam-unwired", Stage.TRAINED, SCAM_SAFETY_1B_V1, ()
        )


def test_manifest_router_uses_server_side_workflow_mapping() -> None:
    class Marker:
        def execute(self, cycle_id, stage, manifest, entries):
            return {"manifest_id": manifest.manifest_id, "marker": cycle_id}

    router = ManifestStageExecutor({"scam_safety": Marker()})
    assert router.execute("mission-scam-route", Stage.DIAGNOSED, SCAM_SAFETY_1B_V1, ()) == {
        "manifest_id": SCAM_SAFETY_1B_V1.manifest_id,
        "marker": "mission-scam-route",
    }

    with pytest.raises(JournalError, match="no configured executor"):
        ManifestStageExecutor({}).execute(
            "mission-scam-route", Stage.DIAGNOSED, SCAM_SAFETY_1B_V1, ()
        )


def test_retained_agent_evidence_is_cryptographically_bound_to_real_trigger() -> None:
    packet = build_scam_failure_packet(
        Path("data/scam_safety/mission.json"),
        Path("data/scam_safety/development-v0.jsonl"),
        Path(f"artifacts/scam-safety/{BASELINE}-development-predictions.jsonl"),
        Path(f"artifacts/scam-safety/{BASELINE}-development-report.json"),
    )
    plan = retained_verified_diagnosis(packet)
    bundle = retained_verified_curriculum({})

    assert "safety-023" in plan["evidence_case_ids"]
    assert hashlib.sha256(bundle["curriculum_jsonl"].encode()).hexdigest() == (
        bundle["authoring_evidence"]["combined_curriculum_sha256"]
    )

    packet["source_hashes"] = {**packet["source_hashes"], "report_sha256": "0" * 64}
    with pytest.raises(JournalError, match="does not match"):
        retained_verified_diagnosis(packet)
