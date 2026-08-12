from __future__ import annotations

from pathlib import Path

import pytest

from nightwatch.contracts import Stage
from nightwatch.journal import JournalError, append_stage, read_journal
from nightwatch.mission_orchestrator import (
    SAFETY_270M_V1,
    MissionManifest,
    advance_mission,
)


class FileJournal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read_cycle(self, cycle_id: str):
        return [entry for entry in read_journal(self.path) if entry.cycle_id == cycle_id]

    def append_stage(self, cycle_id, stage, payload, *, timestamp=None):
        return append_stage(self.path, cycle_id, stage, payload, timestamp=timestamp)


class DeterministicExecutor:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[Stage] = []

    def execute(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        entries: tuple,
    ) -> dict[str, object]:
        self.calls.append(stage)
        payload: dict[str, object] = {
            "manifest_id": manifest.manifest_id,
            "artifact_uri": f"gs://nightwatch/{cycle_id}/{stage.value}.json",
            "artifact_sha256": stage.value.encode().hex().ljust(64, "0")[:64],
        }
        if stage is Stage.EVALUATED:
            payload["accepted"] = self.accepted
            payload["authority"] = "deterministic_policy_v2"
        if stage in {Stage.PROMOTED, Stage.REJECTED}:
            payload["outcome"] = "qualified" if stage is Stage.PROMOTED else "refused"
            payload["deployment_status"] = "qualified_not_deployed"
        return payload


def test_one_call_advances_exactly_one_stage_and_finishes_unattended(tmp_path: Path) -> None:
    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = DeterministicExecutor(accepted=True)

    results = [
        advance_mission(
            "mission-live-001",
            SAFETY_270M_V1.manifest_id,
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
    assert executor.calls == [
        Stage.DIAGNOSED,
        Stage.CURRICULUM_READY,
        Stage.TRAINED,
        Stage.EVALUATED,
        Stage.PROMOTED,
    ]
    assert results[-1].terminal is True
    assert len(journal.read_cycle("mission-live-001")) == 6


def test_terminal_retry_is_noop_and_does_not_repeat_side_effect(tmp_path: Path) -> None:
    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = DeterministicExecutor(accepted=False)
    for _ in range(6):
        result = advance_mission(
            "mission-live-002",
            SAFETY_270M_V1.manifest_id,
            journal=journal,
            executor=executor,
        )
    calls_before_retry = list(executor.calls)

    replay = advance_mission(
        "mission-live-002",
        SAFETY_270M_V1.manifest_id,
        journal=journal,
        executor=executor,
    )

    assert result.stage is Stage.REJECTED
    assert replay.stage is Stage.REJECTED
    assert replay.terminal is True
    assert executor.calls == calls_before_retry


def test_rejects_unapproved_manifest_before_any_write(tmp_path: Path) -> None:
    journal = FileJournal(tmp_path / "mission.jsonl")

    with pytest.raises(JournalError, match="not approved"):
        advance_mission(
            "mission-live-003",
            "attacker-controlled-model",
            journal=journal,
            executor=DeterministicExecutor(),
        )

    assert journal.read_cycle("mission-live-003") == []


def test_rejects_manifest_switch_on_existing_cycle(tmp_path: Path, monkeypatch) -> None:
    from nightwatch import mission_orchestrator

    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = DeterministicExecutor()
    advance_mission(
        "mission-live-004",
        SAFETY_270M_V1.manifest_id,
        journal=journal,
        executor=executor,
    )
    alternate = MissionManifest(
        manifest_id="safety-270m-v2",
        subject=SAFETY_270M_V1.subject,
        trigger_artifact_name=SAFETY_270M_V1.trigger_artifact_name,
        observed_safety_accuracy=SAFETY_270M_V1.observed_safety_accuracy,
        required_safety_accuracy=SAFETY_270M_V1.required_safety_accuracy,
        model_id=SAFETY_270M_V1.model_id,
        model_revision=SAFETY_270M_V1.model_revision,
        seed=SAFETY_270M_V1.seed,
        lora_rank=SAFETY_270M_V1.lora_rank,
        epochs=SAFETY_270M_V1.epochs,
        learning_rate=SAFETY_270M_V1.learning_rate,
        maximum_training_attempts=1,
        maximum_gpu_minutes=20,
    )
    monkeypatch.setitem(mission_orchestrator.APPROVED_MANIFESTS, alternate.manifest_id, alternate)

    with pytest.raises(JournalError, match="does not match"):
        advance_mission(
            "mission-live-004",
            alternate.manifest_id,
            journal=journal,
            executor=executor,
        )


def test_rejects_stage_evidence_with_wrong_manifest_identity(tmp_path: Path) -> None:
    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = DeterministicExecutor()
    advance_mission(
        "mission-live-005",
        SAFETY_270M_V1.manifest_id,
        journal=journal,
        executor=executor,
    )

    class WrongManifestExecutor(DeterministicExecutor):
        def execute(self, cycle_id, stage, manifest, entries):
            return {"manifest_id": "some-other-manifest"}

    with pytest.raises(JournalError, match="wrong manifest"):
        advance_mission(
            "mission-live-005",
            SAFETY_270M_V1.manifest_id,
            journal=journal,
            executor=WrongManifestExecutor(),
        )


def test_expected_stage_retry_replays_same_entry_without_advancing(tmp_path: Path) -> None:
    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = DeterministicExecutor()
    first = advance_mission(
        "mission-live-006",
        SAFETY_270M_V1.manifest_id,
        journal=journal,
        executor=executor,
        expected_stage=Stage.CREATED,
    )

    replay = advance_mission(
        "mission-live-006",
        SAFETY_270M_V1.manifest_id,
        journal=journal,
        executor=executor,
        expected_stage=Stage.CREATED,
    )

    assert replay == first
    assert executor.calls == []
    assert [entry.stage for entry in journal.read_cycle("mission-live-006")] == [Stage.CREATED]


def test_expected_stage_refuses_out_of_order_task(tmp_path: Path) -> None:
    journal = FileJournal(tmp_path / "mission.jsonl")

    with pytest.raises(JournalError, match="expected 'diagnosed'"):
        advance_mission(
            "mission-live-007",
            SAFETY_270M_V1.manifest_id,
            journal=journal,
            executor=DeterministicExecutor(),
            expected_stage=Stage.DIAGNOSED,
        )
