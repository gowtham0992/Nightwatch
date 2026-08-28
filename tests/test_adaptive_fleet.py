from __future__ import annotations

import pytest

from nightwatch.adaptive_fleet import required_specialists
from nightwatch.operator_contracts import build_mission_contract, parse_uploaded_dataset
from test_operator_contracts import adaptive_contract_request, jsonl_bytes


def contract():
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    return build_mission_contract(adaptive_contract_request(dataset.dataset_id), dataset)


def test_required_specialists_are_diagnosis_driven_with_mandatory_regression_guard() -> None:
    assert required_specialists({"required_capabilities": ["target_repair"]}, contract()) == (
        "target_repair",
        "regression_guard",
    )
    assert required_specialists(
        {"required_capabilities": ["target_repair", "safety_boundary"]}, contract()
    ) == ("target_repair", "safety_boundary", "regression_guard")


def test_required_specialists_reject_unknown_capability() -> None:
    with pytest.raises(RuntimeError, match="outside the frozen taxonomy"):
        required_specialists({"required_capabilities": ["deploy_model"]}, contract())
