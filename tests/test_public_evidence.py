from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightwatch.contracts import Stage
from nightwatch.journal import GENESIS_HASH, JournalEntry, JournalError
from nightwatch.public_evidence import (
    PUBLIC_MISSION_ID,
    build_public_snapshot,
    load_public_snapshot,
    validate_public_snapshot,
)


def source_entries() -> list[JournalEntry]:
    payloads = [
        {
            "subject": "small-model incident triage",
            "trigger": {
                "artifact_name": "private-artifact",
                "safety_accuracy": 0.83,
                "required_safety_accuracy": 0.9,
            },
        },
        {
            "actor": "deterministic_policy_analyzer",
            "finding": "below floor",
            "authorized_action": "one intervention",
            "forbidden_action": "weaken policy",
        },
        {
            "architect": {"model": "gemini-3.6-flash", "framework": "google_adk", "generated_examples": 32},
            "curriculum_sha256": "private-curriculum-hash",
            "total_examples": 272,
            "maximum_similarity": {"frozen": {"token_jaccard": 0.22}},
            "leakage_policy": "no overlap",
        },
        {
            "executor": "modal",
            "attempts": [
                {"model_id": "google/gemma-3-270m-it", "model_revision": "private", "training_runtime_seconds": 20.2, "seed": 1},
                {"model_id": "google/gemma-3-1b-it", "model_revision": "private", "training_runtime_seconds": 32.1, "seed": 1},
            ],
            "selection_policy": "fixed",
            "hyperparameter_search": False,
        },
        {
            "evaluator": "deterministic_policy_v2",
            "attempts": [
                {"artifact_name": "private-270", "decision": "refused", "scores": {"safety": {"accuracy": 0.86}}, "critical_misses": []},
                {"artifact_name": "private-1b", "decision": "promoted", "scores": {"safety": {"accuracy": 0.93}}, "critical_misses": []},
            ],
            "evidence": {"case_count": 300, "adjudicated_disagreements": 44, "labels_changed": 21, "manifest_sha256": "private"},
            "retrained_after_adjudication": False,
        },
        {
            "artifact_name": "private-1b",
            "model_id": "google/gemma-3-1b-it",
            "model_revision": "private",
            "qualified_under": "policy_v2",
            "deployment_status": "qualified_not_deployed",
            "scores": {"regression": {"accuracy": 0.86}, "safety": {"accuracy": 0.93}, "target": {"accuracy": 0.7}},
            "regression_label_recall": {"defer": {"accuracy": 0.83}, "investigate": {"accuracy": 0.75}},
            "critical_misses": [],
            "invalid_case_ids": [],
            "promotion_authority": "deterministic_code_only",
        },
    ]
    stages = [
        Stage.CREATED,
        Stage.DIAGNOSED,
        Stage.CURRICULUM_READY,
        Stage.TRAINED,
        Stage.EVALUATED,
        Stage.PROMOTED,
    ]
    hashes = [str(index + 1) * 64 for index in range(6)]
    return [
        JournalEntry(
            cycle_id=PUBLIC_MISSION_ID,
            stage=stage,
            timestamp=f"2026-08-11T00:0{index}:00Z",
            payload=payloads[index],
            previous_hash=GENESIS_HASH if index == 0 else hashes[index - 1],
            entry_hash=hashes[index],
        )
        for index, stage in enumerate(stages)
    ]


def test_public_projection_keeps_decision_evidence_and_removes_private_identity() -> None:
    snapshot = build_public_snapshot(PUBLIC_MISSION_ID, source_entries())
    serialized = json.dumps(snapshot, sort_keys=True)

    assert snapshot["head_hash"] == "6" * 64
    assert snapshot["entries"][-1]["payload"]["scores"]["safety"]["accuracy"] == 0.93
    assert "private" not in serialized
    for forbidden in ["artifact_name", "curriculum_sha256", "manifest_sha256", "model_revision", "report_sha256", "seed"]:
        assert forbidden not in serialized


def test_snapshot_loader_rejects_private_fields_and_broken_links(tmp_path: Path) -> None:
    snapshot = build_public_snapshot(PUBLIC_MISSION_ID, source_entries())
    snapshot["entries"][2]["payload"]["curriculum_sha256"] = "leak"
    path = tmp_path / "public.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(JournalError, match="forbidden"):
        load_public_snapshot(path)

    snapshot["entries"][2]["payload"].pop("curriculum_sha256")
    snapshot["entries"][2]["previous_hash"] = "f" * 64
    with pytest.raises(JournalError, match="chain"):
        validate_public_snapshot(snapshot)


def test_snapshot_loader_rejects_every_non_allowlisted_field() -> None:
    snapshot = build_public_snapshot(PUBLIC_MISSION_ID, source_entries())
    snapshot["entries"][1]["payload"]["operator_notes"] = "must never ship"

    with pytest.raises(JournalError, match="unexpected"):
        validate_public_snapshot(snapshot)
