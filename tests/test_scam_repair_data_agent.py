from __future__ import annotations

from collections import Counter

import pytest

from nightwatch.scam_repair_data_agent import (
    REPAIR_FAMILY_LABELS,
    validate_family_rows,
)


def _row(family: str, label: str, index: int) -> dict[str, object]:
    return {
        "message": f"Original fictional message number {index} for the bounded repair family.",
        "label": label,
        "threat_family": family,
        "rationale": "The observable requested action determines the expected handling label.",
        "safety_critical": False,
    }


def test_validate_family_rows_enforces_exact_family_label_and_count() -> None:
    family = "credential_request_delivery_fraud"
    rows = [_row(family, REPAIR_FAMILY_LABELS[family], index) for index in range(12)]

    validated = validate_family_rows(rows, family=family, expected_count=12)

    assert Counter(row["label"] for row in validated) == Counter({"block": 12})


def test_validate_family_rows_rejects_cross_family_label_drift() -> None:
    family = "unsolicited_link_caution_boundary"
    rows = [_row(family, "caution", index) for index in range(12)]
    rows[-1]["label"] = "routine"

    with pytest.raises(ValueError, match="fixed repair label"):
        validate_family_rows(rows, family=family, expected_count=12)


def test_validate_family_rows_rejects_unknown_family_and_wrong_count() -> None:
    with pytest.raises(ValueError, match="unsupported repair family"):
        validate_family_rows([], family="rewrite_gate", expected_count=12)
    with pytest.raises(ValueError, match="expected 12 rows"):
        validate_family_rows([], family="plausible_notice_harmful_ask", expected_count=12)
