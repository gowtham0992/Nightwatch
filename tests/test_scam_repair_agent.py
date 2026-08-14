from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightwatch.scam_repair_agent import (
    ALLOWED_REPAIR_FAMILIES,
    _prediction_rows,
    build_scam_failure_packet,
    validate_scam_repair_plan,
)


ARTIFACT = "scam-v0-de1e6009-2d77e636-c0e947096d"


def test_failure_packet_contains_only_observed_mismatches() -> None:
    packet = build_scam_failure_packet(
        Path("data/scam_safety/mission.json"),
        Path("data/scam_safety/development-v0.jsonl"),
        Path(f"artifacts/scam-safety/{ARTIFACT}-development-predictions.jsonl"),
        Path(f"artifacts/scam-safety/{ARTIFACT}-development-report.json"),
    )

    assert packet["artifact_name"] == ARTIFACT
    assert packet["error_count"] == 10
    assert len(packet["errors"]) == 10
    assert {row["case_id"] for row in packet["errors"]} == {
        "target-002",
        "target-009",
        "regression-012",
        "regression-015",
        "regression-016",
        "regression-019",
        "regression-021",
        "regression-023",
        "regression-031",
        "safety-023",
    }
    assert all(row["expected_label"] != row["predicted_label"] for row in packet["errors"])
    assert packet["source_hashes"]["development_sha256"]
    assert packet["source_hashes"]["predictions_sha256"]
    assert packet["source_hashes"]["report_sha256"]


def _valid_plan() -> dict[str, object]:
    return {
        "headline": "Explicit harmful asks are underweighted inside plausible notices.",
        "failure_pattern": (
            "The model softens explicit fee and credential requests when a message begins with "
            "credible employment or delivery context."
        ),
        "evidence_case_ids": ["target-009", "safety-023"],
        "repair_objective": (
            "Teach the model to prioritize the requested action over the sender's plausible framing."
        ),
        "repair_families": [
            "plausible_notice_harmful_ask",
            "official_route_safe_contrast",
        ],
        "examples_per_family": 16,
        "protected_behaviors": [
            "Do not block legitimate notices that direct users to a known official route.",
            "Do not turn ordinary work or delivery updates into caution by default.",
        ],
        "success_signal": (
            "Recover block decisions for explicit credential or upfront-fee requests without "
            "increasing benign blocking."
        ),
    }


def test_repair_plan_is_bounded_to_observed_evidence_and_fixed_families() -> None:
    plan = validate_scam_repair_plan(
        _valid_plan(),
        allowed_evidence_ids={"target-009", "safety-023"},
    )

    assert plan["repair_families"] == [
        "plausible_notice_harmful_ask",
        "official_route_safe_contrast",
    ]
    assert plan["examples_per_family"] == 16
    assert set(plan["repair_families"]) <= ALLOWED_REPAIR_FAMILIES


def test_repair_plan_rejects_unobserved_evidence_and_unbounded_changes() -> None:
    raw = _valid_plan()
    raw["evidence_case_ids"] = ["target-009", "sealed-case-001"]
    with pytest.raises(ValueError, match="unobserved evidence"):
        validate_scam_repair_plan(raw, allowed_evidence_ids={"target-009", "safety-023"})


def test_repair_plan_must_address_observed_safety_block_deficits() -> None:
    raw = _valid_plan()
    raw["evidence_case_ids"] = ["target-009", "regression-019"]

    with pytest.raises(ValueError, match="safety block deficit"):
        validate_scam_repair_plan(
            raw,
            allowed_evidence_ids={"target-009", "regression-019", "safety-023"},
            required_safety_ids={"safety-023"},
        )

    raw = _valid_plan()
    raw["repair_families"] = ["plausible_notice_harmful_ask", "rewrite_the_gate"]
    with pytest.raises(ValueError, match="unsupported repair family"):
        validate_scam_repair_plan(raw, allowed_evidence_ids={"target-009", "safety-023"})

    raw = _valid_plan()
    raw["gate_override"] = {"minimum_target_gain": 0}
    with pytest.raises(ValueError, match="keys do not match"):
        validate_scam_repair_plan(raw, allowed_evidence_ids={"target-009", "safety-023"})


def test_failure_packet_rejects_predictions_that_do_not_match_the_report(tmp_path: Path) -> None:
    source = Path(f"artifacts/scam-safety/{ARTIFACT}-development-predictions.jsonl")
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    rows[0]["label"] = "routine"
    tampered = tmp_path / "predictions.jsonl"
    tampered.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match the retained evaluation report"):
        build_scam_failure_packet(
            Path("data/scam_safety/mission.json"),
            Path("data/scam_safety/development-v0.jsonl"),
            tampered,
            Path(f"artifacts/scam-safety/{ARTIFACT}-development-report.json"),
        )


def test_prediction_boundary_allows_family_ids_but_rejects_path_traversal(tmp_path: Path) -> None:
    valid = tmp_path / "valid.jsonl"
    valid.write_text(
        json.dumps(
            {
                "id": "repair-target-credential_request_delivery_fraud-001",
                "label": "block",
                "confidence": 0.9,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert _prediction_rows(valid)[0]["id"] == (
        "repair-target-credential_request_delivery_fraud-001"
    )

    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text(
        json.dumps({"id": "../../artifact", "label": "block", "confidence": 0.9}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid prediction id"):
        _prediction_rows(invalid)
