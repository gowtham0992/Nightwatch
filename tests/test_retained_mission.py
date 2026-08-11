from __future__ import annotations

from pathlib import Path

from nightwatch.contracts import Stage
from nightwatch.journal import append_stage, read_journal
from nightwatch.retained_mission import (
    build_retained_promotion_mission,
    materialize_mission,
)


def test_retained_mission_assembles_real_refusals_and_earned_promotion() -> None:
    mission = build_retained_promotion_mission()

    assert mission.cycle_id == "nightwatch-v2-qualification"
    assert [entry.stage for entry in mission.entries] == [
        Stage.CREATED,
        Stage.DIAGNOSED,
        Stage.CURRICULUM_READY,
        Stage.TRAINED,
        Stage.EVALUATED,
        Stage.PROMOTED,
    ]
    curriculum = mission.entries[2].payload
    assert curriculum["architect"]["model"] == "gemini-3.6-flash"
    assert curriculum["architect"]["generated_examples"] == 32

    training = mission.entries[3].payload
    assert [attempt["model_id"] for attempt in training["attempts"]] == [
        "google/gemma-3-270m-it",
        "google/gemma-3-1b-it",
    ]
    evaluation = mission.entries[4].payload
    assert [attempt["decision"] for attempt in evaluation["attempts"]] == [
        "refused",
        "promoted",
    ]
    promoted = mission.entries[-1].payload
    assert promoted["artifact_name"] == "classifier-1395040c-1e98fdcf-2f16394da7"
    assert promoted["deployment_status"] == "qualified_not_deployed"
    assert promoted["critical_misses"] == []


def test_retained_mission_replays_idempotently_through_hash_chain(tmp_path: Path) -> None:
    mission = build_retained_promotion_mission()
    journal_path = tmp_path / "mission.jsonl"

    def write(cycle_id: str, stage: Stage, payload: dict[str, object]) -> object:
        return append_stage(
            journal_path,
            cycle_id,
            stage,
            payload,
            timestamp=f"2026-08-10T00:0{len(read_journal(journal_path))}:00Z",
        )

    first = materialize_mission(mission, write)
    replay = materialize_mission(mission, write)

    assert len(first) == len(replay) == 6
    assert [entry.entry_hash for entry in replay] == [entry.entry_hash for entry in first]
    assert read_journal(journal_path)[-1].stage is Stage.PROMOTED
