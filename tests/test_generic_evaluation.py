from __future__ import annotations

from nightwatch.generic_evaluation import decide_release, evaluate_predictions, validate_predictions
from test_operator_contracts import contract_request, dataset_rows, jsonl_bytes
from nightwatch.operator_contracts import build_mission_contract, parse_uploaded_dataset


def test_generic_gate_qualifies_only_when_every_frozen_invariant_passes() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(contract_request(dataset.dataset_id), dataset)
    baseline_raw = [
        {"id": row["case"], "label": "routine", "confidence": 0.7}
        for row in dataset_rows()
    ]
    candidate_raw = [
        {"id": row["case"], "label": row["expected"], "confidence": 0.9}
        for row in dataset_rows()
    ]
    baseline = evaluate_predictions("baseline", validate_predictions(baseline_raw, contract, dataset), contract, dataset)
    candidate = evaluate_predictions("candidate", validate_predictions(candidate_raw, contract, dataset), contract, dataset)

    decision = decide_release(baseline, candidate, contract)

    assert decision["accepted"] is True
    assert decision["authority"] == "deterministic_code_only"
    assert decision["failed_invariants"] == []


def test_generic_gate_refuses_a_regression_even_with_perfect_target_and_safety() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(contract_request(dataset.dataset_id), dataset)
    perfect = [{"id": row["case"], "label": row["expected"], "confidence": 0.9} for row in dataset_rows()]
    regressed = [dict(row) for row in perfect]
    regressed[2]["label"] = "block"
    baseline = evaluate_predictions("baseline", validate_predictions(perfect, contract, dataset), contract, dataset)
    candidate = evaluate_predictions("candidate", validate_predictions(regressed, contract, dataset), contract, dataset)

    decision = decide_release(baseline, candidate, contract)

    assert decision["accepted"] is False
    assert "maximum_regression_drop" in decision["failed_invariants"]
