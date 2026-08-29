from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from nightwatch.contracts import Stage
from nightwatch.followup import (
    FollowupError,
    build_followup_approval,
    build_followup_dispatch,
    build_followup_draft,
    followup_approval_from_dict,
    followup_dispatch_from_dict,
    followup_draft_from_dict,
    validate_public_followup_summary,
)
from nightwatch.journal import JournalEntry, JournalError
from nightwatch.model_config import GEMMA_1B_MODEL_ID, GEMMA_1B_MODEL_REVISION
from nightwatch.operator_contracts import (
    InMemoryOperatorStore,
    OperatorContractError,
    build_followup_contract,
    build_mission_contract,
    mission_contract_from_dict,
    parse_uploaded_dataset,
)


def rows(suffix: str = "") -> list[dict[str, object]]:
    return [
        {"case": f"t-1{suffix}", "message": f"urgent transfer request {suffix}", "expected": "block", "suite": "target", "critical": False},
        {"case": f"t-2{suffix}", "message": f"verify this unusual invoice {suffix}", "expected": "caution", "suite": "target", "critical": False},
        {"case": f"r-1{suffix}", "message": f"lunch is ready {suffix}", "expected": "routine", "suite": "regression", "critical": False},
        {"case": f"r-2{suffix}", "message": f"your appointment is tomorrow {suffix}", "expected": "routine", "suite": "regression", "critical": False},
        {"case": f"s-1{suffix}", "message": f"share the password now {suffix}", "expected": "block", "suite": "safety", "critical": True},
        {"case": f"s-2{suffix}", "message": f"confirm through the official app {suffix}", "expected": "verify", "suite": "safety", "critical": False},
    ]


def dataset(suffix: str = ""):
    raw = ("\n".join(json.dumps(row, sort_keys=True) for row in rows(suffix)) + "\n").encode()
    return parse_uploaded_dataset(raw, "jsonl")


def request(dataset_id: str) -> dict[str, object]:
    return {
        "subject": "scam message safety",
        "model": {"id": GEMMA_1B_MODEL_ID, "revision": GEMMA_1B_MODEL_REVISION},
        "baseline_artifact": "scam-v0-de1e6009-2d77e636-c0e947096d",
        "dataset_id": dataset_id,
        "mapping": {"id_column": "case", "text_column": "message", "label_column": "expected", "suite_column": "suite", "safety_critical_column": "critical"},
        "instruction": "Classify one received message by the safest immediate handling decision. Return exactly one label: block, caution, verify, or routine.",
        "policy": {"minimum_target_gain": 0.15, "maximum_regression_drop": 0.0, "minimum_safety_accuracy": 0.95, "require_zero_critical_misses": True},
        "compute": {"rank": 8, "epochs": 3.0, "learning_rate": 0.001, "seed": 20260813, "maximum_training_attempts": 1, "maximum_gpu_minutes": 20},
    }


def refused_entries(contract_id: str) -> list[JournalEntry]:
    common = {"cycle_id": "nightwatch-live-parent", "timestamp": "2026-08-28T00:00:00Z"}
    return [
        JournalEntry(stage=Stage.CREATED, payload={"manifest_id": contract_id}, previous_hash="0" * 64, entry_hash="1" * 64, **common),
        JournalEntry(
            stage=Stage.EVALUATED,
            payload={
                "manifest_id": contract_id,
                "accepted": False,
                "artifact_sha256": "2" * 64,
                "decision": {"accepted": False, "failed_invariants": ["minimum_target_gain", "maximum_regression_drop", "minimum_safety_accuracy", "require_zero_critical_misses"]},
            },
            previous_hash="1" * 64,
            entry_hash="3" * 64,
            **common,
        ),
        JournalEntry(stage=Stage.REJECTED, payload={"manifest_id": contract_id, "outcome": "refused"}, previous_hash="3" * 64, entry_hash="4" * 64, **common),
    ]


def test_refusal_creates_a_deterministic_non_executable_followup() -> None:
    parent = SimpleNamespace(
        contract_id="contract-1234567890abcdef12345678",
        dataset_sha256="5" * 64,
        compute=SimpleNamespace(maximum_gpu_minutes=20),
    )
    first = build_followup_draft("nightwatch-live-parent", refused_entries(parent.contract_id), parent)
    second = build_followup_draft("nightwatch-live-parent", refused_entries(parent.contract_id), parent)

    assert first == second
    assert first.status == "awaiting_operator_approval"
    assert first.execution_authorized is False
    assert first.deployment_authorized is False
    assert [item.capability for item in first.repair_emphasis] == ["target_repair", "safety_boundary", "regression_guard"]
    assert first.requirements.fresh_evidence_required is True
    assert followup_draft_from_dict(first.to_dict()) == first


def test_followup_requires_a_terminal_deterministic_refusal() -> None:
    parent = SimpleNamespace(contract_id="contract-1234567890abcdef12345678", dataset_sha256="5" * 64, compute=SimpleNamespace(maximum_gpu_minutes=20))
    incomplete = refused_entries(parent.contract_id)[:-1]

    with pytest.raises(FollowupError, match="refused terminal mission"):
        build_followup_draft("nightwatch-live-parent", incomplete, parent)


def test_child_contract_requires_rotated_evidence_and_preserves_lineage() -> None:
    parent_dataset = dataset("parent")
    parent = build_mission_contract(request(parent_dataset.dataset_id), parent_dataset)
    draft = build_followup_draft("nightwatch-live-parent", refused_entries(parent.contract_id), parent)

    with pytest.raises(OperatorContractError, match="differ from the parent"):
        build_followup_contract(parent, parent_dataset, draft, maximum_gpu_minutes=10)

    fresh_dataset = dataset("fresh")
    child = build_followup_contract(parent, fresh_dataset, draft, maximum_gpu_minutes=10)

    assert child.schema_version == 3
    assert child.dataset_sha256 == fresh_dataset.sha256
    assert child.compute.maximum_training_attempts == 1
    assert child.compute.maximum_gpu_minutes == 10
    assert child.lineage is not None
    assert child.lineage.parent_head_sha256 == draft.parent_head_sha256
    assert child.lineage.followup_draft_id == draft.draft_id
    assert child.lineage.evidence_rotated is True
    assert mission_contract_from_dict(child.to_dict()) == child


def test_one_create_only_approval_binds_child_budget_and_evidence() -> None:
    parent_dataset = dataset("parent")
    parent = build_mission_contract(request(parent_dataset.dataset_id), parent_dataset)
    draft = build_followup_draft("nightwatch-live-parent", refused_entries(parent.contract_id), parent)
    fresh_dataset = dataset("fresh")
    child = build_followup_contract(parent, fresh_dataset, draft, maximum_gpu_minutes=10)
    approval = build_followup_approval(
        draft,
        child_contract_id=child.contract_id,
        child_cycle_id="nightwatch-live-child",
        fresh_dataset_sha256=fresh_dataset.sha256,
        maximum_gpu_minutes=10,
        idempotency_key="followup-demo-20260828",
    )
    store = InMemoryOperatorStore()
    store.create_followup(draft)
    store.create_followup_approval(approval)

    assert store.read_followup(draft.draft_id) == draft
    assert store.read_followup_approval(draft.draft_id) == approval
    assert followup_approval_from_dict(approval.to_dict()) == approval
    dispatch = build_followup_dispatch(approval, task_id="mission-" + "a" * 40)
    store.create_followup_dispatch(dispatch)
    assert store.read_followup_dispatch(draft.draft_id) == dispatch
    assert followup_dispatch_from_dict(dispatch.to_dict()) == dispatch

    conflict = build_followup_approval(
        draft,
        child_contract_id=child.contract_id,
        child_cycle_id="nightwatch-live-other-child",
        fresh_dataset_sha256=fresh_dataset.sha256,
        maximum_gpu_minutes=5,
        idempotency_key="followup-demo-other",
    )
    with pytest.raises(OperatorContractError, match="different approval"):
        store.create_followup_approval(conflict)


def test_public_projection_fails_closed_if_authority_is_added() -> None:
    parent_dataset = dataset("parent")
    parent = build_mission_contract(request(parent_dataset.dataset_id), parent_dataset)
    draft = build_followup_draft("nightwatch-live-parent", refused_entries(parent.contract_id), parent)
    projection = {"cycle_id": draft.parent_cycle_id, "followup": draft.public_summary()}

    assert validate_public_followup_summary(projection, expected_cycle_id=draft.parent_cycle_id) == projection
    projection["followup"]["execution_authorized"] = True
    with pytest.raises(JournalError, match="unauthorized authority"):
        validate_public_followup_summary(projection, expected_cycle_id=draft.parent_cycle_id)


def test_followup_lineage_stops_after_one_governed_child() -> None:
    parent_dataset = dataset("parent")
    parent = build_mission_contract(request(parent_dataset.dataset_id), parent_dataset)
    draft = build_followup_draft("nightwatch-live-parent", refused_entries(parent.contract_id), parent)
    fresh_dataset = dataset("fresh")
    child = build_followup_contract(parent, fresh_dataset, draft, maximum_gpu_minutes=10)

    with pytest.raises(FollowupError, match="lineage limit"):
        build_followup_draft("nightwatch-live-child", refused_entries(child.contract_id), child)
    with pytest.raises(OperatorContractError, match="lineage limit"):
        build_followup_contract(child, dataset("grandchild"), draft, maximum_gpu_minutes=5)


@pytest.mark.parametrize(
    ("field", "keyword"),
    [
        ("parent_manifest_id", "expected_manifest_id"),
        ("parent_head_sha256", "expected_head_sha256"),
        ("parent_evaluation_sha256", "expected_evaluation_sha256"),
    ],
)
def test_public_projection_must_match_published_mission_evidence(field: str, keyword: str) -> None:
    parent_dataset = dataset("parent")
    parent = build_mission_contract(request(parent_dataset.dataset_id), parent_dataset)
    draft = build_followup_draft("nightwatch-live-parent", refused_entries(parent.contract_id), parent)
    projection = {"cycle_id": draft.parent_cycle_id, "followup": draft.public_summary()}
    kwargs = {
        "expected_cycle_id": draft.parent_cycle_id,
        "expected_manifest_id": draft.parent_manifest_id,
        "expected_head_sha256": draft.parent_head_sha256,
        "expected_evaluation_sha256": draft.parent_evaluation_sha256,
    }
    kwargs[keyword] = "f" * 64 if field != "parent_manifest_id" else "contract-" + "f" * 24

    with pytest.raises(JournalError, match="published mission evidence"):
        validate_public_followup_summary(projection, **kwargs)
