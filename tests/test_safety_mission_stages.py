from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nightwatch.contracts import Stage
from nightwatch.journal import GENESIS_HASH, JournalEntry, JournalError, append_stage, read_journal
from nightwatch.mission_orchestrator import SAFETY_270M_V1, advance_mission
from nightwatch.safety_mission_stages import SafetyQualificationStageExecutor
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
            raise JournalError("conflicting artifact")
        return existing


def write_inputs(root: Path) -> dict[str, Path]:
    report = {
        "artifact_name": SAFETY_270M_V1.trigger_artifact_name,
        "dev_evaluation": {
            "scores": {
                "safety": {
                    "accuracy": SAFETY_270M_V1.observed_safety_accuracy,
                    "correct": 25,
                    "total": 30,
                }
            }
        },
        "dev_assessment": {"accepted": False, "reasons": ["below floor"]},
    }
    paths = {
        "baseline_report_path": root / "baseline.json",
        "base_curriculum_path": root / "base.jsonl",
        "development_evidence_path": root / "development.jsonl",
        "frozen_evidence_path": root / "frozen.jsonl",
    }
    paths["baseline_report_path"].write_text(json.dumps(report))
    paths["base_curriculum_path"].write_text('{"prompt":"base","label":"defer"}\n')
    paths["development_evidence_path"].write_text('{"id":"dev"}\n')
    paths["frozen_evidence_path"].write_text('{"id":"frozen"}\n')
    return paths


def test_diagnosis_is_derived_from_the_pinned_real_trigger(tmp_path: Path) -> None:
    executor = SafetyQualificationStageExecutor(MemoryArtifacts(), **write_inputs(tmp_path))

    payload = executor.execute(
        "mission-live-101",
        Stage.DIAGNOSED,
        SAFETY_270M_V1,
        (),
    )

    assert "25/30" in payload["finding"]
    assert payload["assessment"]["accepted"] is False
    assert payload["manifest_id"] == SAFETY_270M_V1.manifest_id
    assert payload["artifact_uri"].startswith("gs://private/")


def test_curriculum_retry_reads_artifact_without_calling_gemini_twice(tmp_path: Path) -> None:
    calls = 0

    def generator(base: Path, development: Path, frozen: Path):
        nonlocal calls
        calls += 1
        curriculum = '{"prompt":"generated","label":"page_now"}\n'
        return curriculum, {
            "teacher_model": "gemini-3.6-flash",
            "output_sha256": hashlib.sha256(curriculum.encode()).hexdigest(),
            "generated_examples": 32,
            "total_examples": 272,
            "maximum_similarity": {
                "development": {"token_jaccard": 0.2},
                "frozen": {"token_jaccard": 0.2},
            },
        }

    executor = SafetyQualificationStageExecutor(
        MemoryArtifacts(),
        curriculum_generator=generator,
        **write_inputs(tmp_path),
    )

    first = executor.execute(
        "mission-live-102",
        Stage.CURRICULUM_READY,
        SAFETY_270M_V1,
        (),
    )
    replay = executor.execute(
        "mission-live-102",
        Stage.CURRICULUM_READY,
        SAFETY_270M_V1,
        (),
    )

    assert replay == first
    assert calls == 1
    assert first["architect"] == {
        "framework": "google_adk",
        "model": "gemini-3.6-flash",
        "generated_examples": 32,
    }


def test_curriculum_fails_closed_on_teacher_or_digest_drift(tmp_path: Path) -> None:
    def bad_generator(*_paths):
        return "content\n", {
            "teacher_model": "different-model",
            "output_sha256": "0" * 64,
            "generated_examples": 32,
            "maximum_similarity": {},
        }

    executor = SafetyQualificationStageExecutor(
        MemoryArtifacts(),
        curriculum_generator=bad_generator,
        **write_inputs(tmp_path),
    )

    with pytest.raises(JournalError, match="fixed contract"):
        executor.execute(
            "mission-live-103",
            Stage.CURRICULUM_READY,
            SAFETY_270M_V1,
            (),
        )


def test_executor_refuses_unwired_paid_stage(tmp_path: Path) -> None:
    executor = SafetyQualificationStageExecutor(MemoryArtifacts(), **write_inputs(tmp_path))

    with pytest.raises(JournalError, match="not wired"):
        executor.execute("mission-live-104", Stage.TRAINED, SAFETY_270M_V1, ())


def test_fresh_mission_advances_through_real_pretraining_contract(tmp_path: Path) -> None:
    class FileJournal:
        def __init__(self, path: Path) -> None:
            self.path = path

        def read_cycle(self, cycle_id: str):
            return [row for row in read_journal(self.path) if row.cycle_id == cycle_id]

        def append_stage(self, cycle_id, stage, payload, *, timestamp=None):
            return append_stage(self.path, cycle_id, stage, payload, timestamp=timestamp)

    def generator(*_paths):
        curriculum = '{"prompt":"generated","label":"page_now"}\n'
        return curriculum, {
            "teacher_model": "gemini-3.6-flash",
            "output_sha256": hashlib.sha256(curriculum.encode()).hexdigest(),
            "generated_examples": 32,
            "total_examples": 272,
            "maximum_similarity": {
                "development": {"token_jaccard": 0.2},
                "frozen": {"token_jaccard": 0.2},
            },
        }

    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = SafetyQualificationStageExecutor(
        MemoryArtifacts(),
        curriculum_generator=generator,
        **write_inputs(tmp_path),
    )

    advances = [
        advance_mission(
            "mission-live-105",
            SAFETY_270M_V1.manifest_id,
            journal=journal,
            executor=executor,
        )
        for _ in range(3)
    ]

    assert [advance.stage for advance in advances] == [
        Stage.CREATED,
        Stage.DIAGNOSED,
        Stage.CURRICULUM_READY,
    ]
    entries = journal.read_cycle("mission-live-105")
    assert entries[0].payload["deployment_authorized"] is False
    assert entries[1].payload["artifact_sha256"]
    assert entries[2].payload["architect"]["framework"] == "google_adk"


def test_policy_v2_reproduces_real_270m_refusal_and_terminal_record() -> None:
    artifacts = MemoryArtifacts()
    predictions = Path(
        "artifacts/classifier-1395040c-1e98fdcf-74d932a468-dev-predictions.jsonl"
    ).read_text()
    artifacts.create(
        "mission-live-106",
        Stage.TRAINED,
        SAFETY_270M_V1.manifest_id,
        {
            "journal_payload": {"executor": "modal", "attempts": []},
            "modal_result": {
                "artifact_name": SAFETY_270M_V1.trigger_artifact_name,
                "config": {
                    "model_id": SAFETY_270M_V1.model_id,
                    "model_revision": SAFETY_270M_V1.model_revision,
                },
                "predictions_jsonl": predictions,
            },
        },
    )
    executor = SafetyQualificationStageExecutor(artifacts)

    evaluated = executor.execute(
        "mission-live-106",
        Stage.EVALUATED,
        SAFETY_270M_V1,
        (),
    )
    evaluated_entry = JournalEntry(
        cycle_id="mission-live-106",
        stage=Stage.EVALUATED,
        timestamp="2026-08-11T00:00:00Z",
        payload=evaluated,
        previous_hash=GENESIS_HASH,
        entry_hash="a" * 64,
    )
    terminal = executor.execute(
        "mission-live-106",
        Stage.REJECTED,
        SAFETY_270M_V1,
        (evaluated_entry,),
    )

    assert evaluated["accepted"] is False
    assert evaluated["attempts"][0]["decision"] == "refused"
    assert terminal["outcome"] == "refused"
    assert terminal["deployment_status"] == "refused_not_deployed"
    assert terminal["promotion_authority"] == "deterministic_code_only"
