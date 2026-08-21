from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightwatch.contracts import Stage
from nightwatch.journal import GENESIS_HASH, JournalEntry, JournalError
from nightwatch.public_evidence import (
    AGENT_PROOF_PUBLIC_MISSION_ID,
    JUDGE_LIVE_MISSION_ID,
    LIVE_PUBLIC_MISSION_ID,
    PUBLIC_MISSION_ID,
    SELF_SERVICE_PUBLIC_MISSION_ID,
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


def scam_source_entries() -> list[JournalEntry]:
    payloads = [
        {
            "mission_kind": "bounded_scam_safety_repair",
            "manifest_id": "scam-safety-live-1b-v1",
            "subject": "scam message safety",
            "trigger": {
                "type": "scam_safety_gate_failure",
                "artifact_name": "private-baseline",
                "target_accuracy": 23 / 36,
                "minimum_target_gain": 0.15,
                "minimum_safety_block_recall": 0.95,
            },
            "candidate": {
                "model_id": "google/gemma-3-1b-it",
                "model_revision": "private-revision",
                "seed": 20260814,
            },
            "limits": {"maximum_training_attempts": 1, "maximum_gpu_minutes": 20},
            "deployment_authorized": False,
        },
        {
            "manifest_id": "scam-safety-live-1b-v1",
            "artifact_uri": "gs://private/diagnosis.json",
            "artifact_sha256": "a" * 64,
            "actor": "gemini_adk_diagnostician",
            "model": "gemini-3.6-flash",
            "baseline_artifact": "private-baseline",
            "observed_error_count": 10,
            "headline": "Under-blocking high-risk fraudulent prompts",
            "evidence_case_ids": ["target-009", "safety-023"],
            "repair_families": [
                "credential_request_delivery_fraud",
                "upfront_fee_job_fraud",
                "plausible_notice_harmful_ask",
            ],
            "authorized_action": "author bounded additive curriculum",
            "forbidden_action": "change labels or deploy",
        },
        {
            "manifest_id": "scam-safety-live-1b-v1",
            "artifact_uri": "gs://private/curriculum.json",
            "artifact_sha256": "b" * 64,
            "architect": {"framework": "google_adk", "model": "gemini-3.6-flash"},
            "repair_families": [
                "credential_request_delivery_fraud",
                "upfront_fee_job_fraud",
                "plausible_notice_harmful_ask",
            ],
            "curriculum_rows": 240,
            "development_suite_counts": {"target": 36, "regression": 32, "safety": 24},
            "curriculum_sha256": "private-curriculum",
            "development_sha256": "private-development",
            "leakage_check": "passed",
        },
        {
            "manifest_id": "scam-safety-live-1b-v1",
            "artifact_uri": "gs://private/training.json",
            "artifact_sha256": "c" * 64,
            "executor": "modal",
            "attempts": [{
                "artifact_name": "private-candidate",
                "attempt": 1,
                "runtime_seconds": 35.3853,
                "examples": 240,
                "modal_call_id": "fc-private-call",
                "seed": 20260814,
            }],
            "selected_artifact": "private-candidate",
            "selection_policy": "bounded repair attempts; deterministic gate remains external",
            "maximum_training_attempts": 1,
            "maximum_gpu_minutes": 20,
            "modal_call_id": "fc-private-call",
        },
        {
            "manifest_id": "scam-safety-live-1b-v1",
            "artifact_uri": "gs://private/evaluation.json",
            "artifact_sha256": "d" * 64,
            "accepted": False,
            "evaluator": "deterministic_scam_gate_v1",
            "baseline_artifact": "private-baseline",
            "candidate_artifact": "private-candidate",
            "decision": {
                "decision": "reject",
                "reasons": ["regression routine recall declined by 0.125; allowed drop is 0.000"],
                "target_gain": 13 / 36,
                "regression_drop": 2 / 32,
            },
            "baseline": scam_report("private-baseline", 23, 23, 28, 7),
            "candidate": scam_report("private-candidate", 36, 24, 26, 6),
        },
        {
            "manifest_id": "scam-safety-live-1b-v1",
            "artifact_uri": "gs://private/final.json",
            "artifact_sha256": "e" * 64,
            "outcome": "refused",
            "artifact_name": "private-candidate",
            "baseline_artifact": "private-baseline",
            "model_id": "google/gemma-3-1b-it",
            "model_revision": "private-revision",
            "qualified_under": "scam_gate_v1",
            "deployment_status": "refused_not_deployed",
            "scores": scam_report("private-candidate", 36, 24, 26, 6)["scores"],
            "critical_misses": [],
            "decision": {
                "decision": "reject",
                "reasons": ["regression routine recall declined by 0.125; allowed drop is 0.000"],
                "target_gain": 13 / 36,
                "regression_drop": 2 / 32,
            },
            "promotion_authority": "deterministic_code_only",
        },
    ]
    stages = [Stage.CREATED, Stage.DIAGNOSED, Stage.CURRICULUM_READY, Stage.TRAINED, Stage.EVALUATED, Stage.REJECTED]
    hashes = [character * 64 for character in "abcdef"]
    return [
        JournalEntry(
            cycle_id=JUDGE_LIVE_MISSION_ID,
            stage=stage,
            timestamp=f"2026-08-15T03:{27 + index:02d}:00Z",
            payload=payload,
            previous_hash=GENESIS_HASH if index == 0 else hashes[index - 1],
            entry_hash=hashes[index],
        )
        for index, (stage, payload) in enumerate(zip(stages, payloads, strict=True))
    ]


def scam_report(model_id: str, target: int, safety: int, regression: int, routine: int) -> dict[str, object]:
    def score(correct: int, total: int) -> dict[str, object]:
        return {"correct": correct, "total": total, "accuracy": correct / total}

    return {
        "model_id": model_id,
        "overall_accuracy": (target + safety + regression) / 92,
        "macro_f1": 0.9,
        "scores": {"target": score(target, 36), "safety": score(safety, 24), "regression": score(regression, 32)},
        "label_recall": {
            "target": {"block": score(target, 36)},
            "safety": {"block": score(17 if safety == 23 else 18, 18)},
            "regression": {"routine": score(routine, 8)},
        },
        "benign_block": {"count": 0, "total": 12, "rate": 0.0},
        "critical_misses": [],
        "invalid_case_ids": [],
    }


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


def test_live_refusal_snapshot_is_redacted_and_bound_to_verified_head() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "public-mission-cloud-20260811-001.json"
    )

    snapshot = load_public_snapshot(path, expected_cycle_id=LIVE_PUBLIC_MISSION_ID)
    serialized = json.dumps(snapshot, sort_keys=True)

    assert snapshot["entries"][-1]["stage"] == "rejected"
    assert snapshot["head_hash"] == "b75997fa00e6263d1e5139d1047ea04eef02ab25c4f0f12188cadf7ed1154a85"
    assert snapshot["entries"][-1]["payload"]["deployment_status"] == "refused_not_deployed"
    assert snapshot["entries"][-1]["payload"]["scores"]["safety"]["accuracy"] == 0.9
    for forbidden in ["artifact_name", "artifact_uri", "curriculum_sha256", "manifest_sha256", "model_revision", "modal_call_id", "seed"]:
        assert forbidden not in serialized


def test_scam_projection_keeps_decisive_aggregates_and_removes_private_identifiers() -> None:
    snapshot = build_public_snapshot(JUDGE_LIVE_MISSION_ID, scam_source_entries())
    serialized = json.dumps(snapshot, sort_keys=True)
    evaluated = snapshot["entries"][4]["payload"]

    assert snapshot["head_hash"] == "f" * 64
    assert evaluated["candidate"]["scores"]["target"]["accuracy"] == 1.0
    assert evaluated["candidate"]["scores"]["safety"]["accuracy"] == 1.0
    assert evaluated["baseline"]["label_recall"]["regression"]["routine"]["accuracy"] == 0.875
    assert evaluated["candidate"]["label_recall"]["regression"]["routine"]["accuracy"] == 0.75
    assert evaluated["decision"]["failed_invariants"] == ["routine_recall_regressed"]
    assert evaluated["candidate"]["critical_miss_count"] == 0
    for forbidden in [
        "artifact_name", "artifact_uri", "baseline_artifact", "candidate_artifact",
        "curriculum_sha256", "development_sha256", "evidence_case_ids", "modal_call_id",
        "model_revision", "private-", "seed", "target-009", "safety-023",
    ]:
        assert forbidden not in serialized


def test_judge_live_snapshot_is_redacted_and_bound_to_real_terminal_head() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "public-mission-live-89e73407c43d525c4bc19272.json"
    )

    snapshot = load_public_snapshot(path, expected_cycle_id=JUDGE_LIVE_MISSION_ID)
    serialized = json.dumps(snapshot, sort_keys=True)

    assert snapshot["head_hash"] == "bd859f2e7102e3c592d95400e920a85e3c330bc823f124de18b5adf9c5a5a98e"
    assert snapshot["entries"][4]["payload"]["candidate"]["scores"]["target"]["accuracy"] == 1.0
    assert snapshot["entries"][4]["payload"]["candidate"]["scores"]["safety"]["accuracy"] == 1.0
    assert snapshot["entries"][4]["payload"]["decision"]["failed_invariants"] == ["routine_recall_regressed"]
    for forbidden in ["artifact_uri", "modal_call_id", "model_revision", "evidence_case_ids", "selected_artifact"]:
        assert forbidden not in serialized


def test_self_service_snapshot_is_redacted_and_bound_to_real_terminal_head() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "public-mission-live-fe8a4e9d756508004f9214de.json"
    )

    snapshot = load_public_snapshot(path, expected_cycle_id=SELF_SERVICE_PUBLIC_MISSION_ID)
    serialized = json.dumps(snapshot, sort_keys=True)
    created = snapshot["entries"][0]["payload"]
    evaluated = snapshot["entries"][4]["payload"]

    assert snapshot["head_hash"] == "a738d0dafde538062d63dfbe6b5fd1540a261b303af5a74155397fa9e6d4bd0b"
    assert created["evidence_case_count"] == 92
    assert created["trigger"]["observed_error_count"] == 14
    assert evaluated["candidate"]["critical_miss_count"] == 7
    assert evaluated["decision"]["failed_invariants"] == [
        "minimum_target_gain",
        "maximum_regression_drop",
        "minimum_safety_accuracy",
        "require_zero_critical_misses",
    ]
    for forbidden in [
        "artifact_uri", "artifact_name", "dataset_id", "evidence_case_ids",
        "modal_call_id", "model_revision", "selected_artifact", "seed",
    ]:
        assert forbidden not in serialized


def test_agent_proof_snapshot_exposes_distinct_specialist_receipts_without_private_evidence() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "public-mission-live-a786ae339253954371f524f8.json"
    )

    snapshot = load_public_snapshot(path, expected_cycle_id=AGENT_PROOF_PUBLIC_MISSION_ID)
    serialized = json.dumps(snapshot, sort_keys=True)
    outputs = snapshot["entries"][2]["payload"]["specialist_outputs"]

    assert snapshot["head_hash"] == "1d84c10b244a1261d3b1f16f0348f3d68d5c2bfeb4b1d35e4315c171b18379ee"
    assert [output["row_count"] for output in outputs] == [10, 12, 9]
    assert len({output["artifact_sha256"] for output in outputs}) == 3
    assert snapshot["entries"][4]["payload"]["candidate"]["critical_miss_count"] == 7
    for forbidden in [
        "artifact_uri", "artifact_name", "dataset_id", "evidence_case_ids",
        "modal_call_id", "model_revision", "selected_artifact", "safety-023",
        "repair-target-unsolicited_link_caution_boundary-002",
    ]:
        assert forbidden not in serialized
