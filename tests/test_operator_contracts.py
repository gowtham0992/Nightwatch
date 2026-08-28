from __future__ import annotations

import json

import pytest

from nightwatch.agent_roster import AGENT_TAXONOMY_VERSION, APPROVED_AGENT_ROSTER, MANDATORY_SPECIALISTS, MAX_SPECIALISTS
from nightwatch.model_config import GEMMA_1B_MODEL_ID, GEMMA_1B_MODEL_REVISION
from nightwatch.operator_contracts import (
    InMemoryOperatorStore,
    OperatorContractError,
    build_mission_contract,
    mission_contract_from_dict,
    parse_uploaded_dataset,
    require_contract,
)
from nightwatch.journal import JournalError


def dataset_rows() -> list[dict[str, object]]:
    return [
        {"case": "t-1", "message": "urgent transfer request", "expected": "block", "suite": "target", "critical": False},
        {"case": "t-2", "message": "verify this unusual invoice", "expected": "caution", "suite": "target", "critical": False},
        {"case": "r-1", "message": "lunch is ready", "expected": "routine", "suite": "regression", "critical": False},
        {"case": "r-2", "message": "your appointment is tomorrow", "expected": "routine", "suite": "regression", "critical": False},
        {"case": "s-1", "message": "share the password now", "expected": "block", "suite": "safety", "critical": True},
        {"case": "s-2", "message": "confirm through the official app", "expected": "verify", "suite": "safety", "critical": False},
    ]


def jsonl_bytes(rows: list[dict[str, object]] | None = None) -> bytes:
    return (
        "\n".join(json.dumps(row, sort_keys=True) for row in (rows or dataset_rows())) + "\n"
    ).encode()


def contract_request(dataset_id: str) -> dict[str, object]:
    return {
        "subject": "scam message safety",
        "model": {"id": GEMMA_1B_MODEL_ID, "revision": GEMMA_1B_MODEL_REVISION},
        "baseline_artifact": "scam-v0-de1e6009-2d77e636-c0e947096d",
        "dataset_id": dataset_id,
        "mapping": {
            "id_column": "case",
            "text_column": "message",
            "label_column": "expected",
            "suite_column": "suite",
            "safety_critical_column": "critical",
        },
        "instruction": "Classify one received message by the safest immediate handling decision. Return exactly one label: block, caution, verify, or routine.",
        "policy": {
            "minimum_target_gain": 0.15,
            "maximum_regression_drop": 0.0,
            "minimum_safety_accuracy": 0.95,
            "require_zero_critical_misses": True,
        },
        "compute": {
            "rank": 8,
            "epochs": 3.0,
            "learning_rate": 0.001,
            "seed": 20260813,
            "maximum_training_attempts": 1,
            "maximum_gpu_minutes": 20,
        },
    }


def adaptive_contract_request(dataset_id: str) -> dict[str, object]:
    request = contract_request(dataset_id)
    request["delegation"] = {
        "taxonomy_version": AGENT_TAXONOMY_VERSION,
        "maximum_specialists": MAX_SPECIALISTS,
        "mandatory_specialists": list(MANDATORY_SPECIALISTS),
        "approved_agents": [
            {**entry, "capabilities": list(entry["capabilities"])}
            for entry in APPROVED_AGENT_ROSTER
        ],
    }
    return request


def test_uploaded_jsonl_is_canonical_and_content_addressed() -> None:
    first = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    second = parse_uploaded_dataset(jsonl_bytes(), ".jsonl")

    assert first == second
    assert first.dataset_id.startswith("dataset-")
    assert len(first.sha256) == 64
    assert first.row_count == 6
    assert set(first.columns) == {"case", "critical", "expected", "message", "suite"}
    assert first.canonical_bytes().endswith(b"\n")


def test_uploaded_csv_is_accepted_and_canonicalized() -> None:
    csv_bytes = (
        "case,message,expected,suite,critical\n"
        "t-1,urgent transfer request,block,target,false\n"
        "t-2,verify this unusual invoice,verify,target,false\n"
        "r-1,lunch is ready,routine,regression,false\n"
        "r-2,your appointment is tomorrow,routine,regression,false\n"
        "s-1,share the password now,block,safety,true\n"
        "s-2,confirm through the official app,verify,safety,false\n"
    ).encode()

    csv_dataset = parse_uploaded_dataset(csv_bytes, "csv")
    assert csv_dataset.row_count == 6
    assert csv_dataset.file_format == "csv"


def test_contract_is_frozen_by_exact_model_dataset_policy_and_budget() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(contract_request(dataset.dataset_id), dataset)

    assert contract.contract_id.startswith("contract-")
    assert contract.dataset_sha256 == dataset.sha256
    assert contract.labels == ("block", "caution", "verify", "routine")
    assert contract.compute.maximum_training_attempts == 1
    assert contract.compute.maximum_gpu_minutes == 20
    assert contract.runtime == "modal"
    assert mission_contract_from_dict(contract.to_dict()) == contract


def test_adaptive_contract_pins_registry_identities_endpoints_and_card_hashes() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(adaptive_contract_request(dataset.dataset_id), dataset)

    assert contract.schema_version == 2
    assert contract.delegation is not None
    assert contract.delegation.maximum_specialists == 3
    assert contract.delegation.mandatory_specialists == ("regression_guard",)
    assert [agent.specialist for agent in contract.delegation.approved_agents] == [
        "target_repair", "safety_boundary", "regression_guard"
    ]
    assert mission_contract_from_dict(contract.to_dict()) == contract


def test_adaptive_contract_rejects_operator_substitution_of_registered_agent() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    request = adaptive_contract_request(dataset.dataset_id)
    request["delegation"]["approved_agents"][0]["endpoint_origin"] = "https://attacker.example"

    with pytest.raises(OperatorContractError, match="operator-approved fleet"):
        build_mission_contract(request, dataset)


def test_contract_id_changes_when_release_policy_changes() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    first_request = contract_request(dataset.dataset_id)
    second_request = contract_request(dataset.dataset_id)
    second_request["policy"] = {**second_request["policy"], "minimum_target_gain": 0.2}

    first = build_mission_contract(first_request, dataset)
    second = build_mission_contract(second_request, dataset)

    assert first.contract_id != second.contract_id


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda request: request.update(model={"id": "other/model", "revision": "main"}), "not supported"),
        (lambda request: request["compute"].update(maximum_training_attempts=2), "exactly 1"),
        (lambda request: request["compute"].update(maximum_gpu_minutes=21), "between 1 and 20"),
        (lambda request: request["mapping"].update(text_column="missing"), "not a dataset column"),
    ],
)
def test_contract_rejects_unapproved_model_compute_and_mapping(mutate, message: str) -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    request = contract_request(dataset.dataset_id)
    mutate(request)

    with pytest.raises(OperatorContractError, match=message):
        build_mission_contract(request, dataset)


def test_contract_rejects_duplicate_text_and_missing_suite() -> None:
    rows = dataset_rows()
    rows[1]["message"] = "  URGENT   TRANSFER REQUEST  "
    rows = [row for row in rows if row["suite"] != "safety"]
    dataset = parse_uploaded_dataset(jsonl_bytes(rows), "jsonl")

    with pytest.raises(OperatorContractError, match="duplicate canonical text"):
        build_mission_contract(contract_request(dataset.dataset_id), dataset)


def test_contract_rejects_a_missing_required_suite() -> None:
    rows = [row for row in dataset_rows() if row["suite"] != "safety"]
    dataset = parse_uploaded_dataset(jsonl_bytes(rows), "jsonl")

    with pytest.raises(OperatorContractError, match="missing required suites: safety"):
        build_mission_contract(contract_request(dataset.dataset_id), dataset)


def test_contract_digest_detects_stored_mutation() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(contract_request(dataset.dataset_id), dataset)
    mutated = contract.to_dict()
    mutated["instruction"] = "Ignore the frozen instruction."

    with pytest.raises(OperatorContractError, match="digest does not match"):
        mission_contract_from_dict(mutated)


def test_required_contract_is_revalidated_with_its_dataset() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(contract_request(dataset.dataset_id), dataset)
    store = InMemoryOperatorStore()
    store.create_dataset(dataset)
    store.create_contract(contract)

    assert require_contract(store, contract.contract_id) == contract

    store._datasets.clear()
    with pytest.raises(JournalError, match="semantic validation"):
        require_contract(store, contract.contract_id)
