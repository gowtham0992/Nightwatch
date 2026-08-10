from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightwatch.contracts import Stage
from nightwatch.journal import JournalError, append_stage, read_journal


def test_journal_is_idempotent_for_same_stage_and_payload(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    first = append_stage(path, "cycle-1", Stage.CREATED, {"baseline": "v1"}, timestamp="2026-08-09T00:00:00Z")
    replay = append_stage(path, "cycle-1", Stage.CREATED, {"baseline": "v1"}, timestamp="later-is-ignored")

    assert replay == first
    assert len(read_journal(path)) == 1


def test_completed_cycle_can_be_replayed_without_new_entries(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    stages = [
        Stage.CREATED,
        Stage.DIAGNOSED,
        Stage.CURRICULUM_READY,
        Stage.TRAINED,
        Stage.EVALUATED,
        Stage.PROMOTED,
    ]
    for index, stage in enumerate(stages):
        append_stage(path, "cycle-1", stage, {"index": index}, timestamp=f"2026-08-09T00:0{index}:00Z")
    for index, stage in enumerate(stages):
        append_stage(path, "cycle-1", stage, {"index": index}, timestamp="ignored")

    assert [entry.stage for entry in read_journal(path)] == stages


def test_journal_rejects_skipped_transition(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    append_stage(path, "cycle-1", Stage.CREATED, {}, timestamp="2026-08-09T00:00:00Z")

    with pytest.raises(JournalError, match="invalid transition"):
        append_stage(path, "cycle-1", Stage.TRAINED, {}, timestamp="2026-08-09T00:01:00Z")


def test_journal_detects_payload_tampering(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    append_stage(path, "cycle-1", Stage.CREATED, {"baseline": "v1"}, timestamp="2026-08-09T00:00:00Z")
    row = json.loads(path.read_text(encoding="utf-8"))
    row["payload"]["baseline"] = "attacker-version"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(JournalError, match="broken journal hash chain"):
        read_journal(path)
