from __future__ import annotations

from nightwatch.evidence_audit_agent import validate_batch_judgments


def _packet() -> list[dict[str, str]]:
    return [
        {"audit_id": "audit-a", "prompt": "A confirmed production outage affects every customer."},
        {"audit_id": "audit-b", "prompt": "A staging test warning cleared after recovery."},
    ]


def test_batch_validation_preserves_exact_blind_packet_coverage() -> None:
    judgments = [
        {
            "audit_id": "audit-b",
            "label": "defer",
            "rationale": "The event is explicitly staging-only and recovery is confirmed.",
            "ambiguous": False,
        },
        {
            "audit_id": "audit-a",
            "label": "page_now",
            "rationale": "The evidence confirms complete production customer impact.",
            "ambiguous": False,
        },
    ]

    validated = validate_batch_judgments(_packet(), judgments)

    assert [row["audit_id"] for row in validated] == ["audit-a", "audit-b"]


def test_batch_validation_rejects_coverage_or_schema_drift() -> None:
    valid = {
        "audit_id": "audit-a",
        "label": "page_now",
        "rationale": "The evidence confirms complete production customer impact.",
        "ambiguous": False,
    }
    bad_cases = [
        ([valid], "coverage"),
        ([valid, valid], "duplicate"),
        ([valid, {**valid, "audit_id": "audit-b", "label": "wake_someone"}], "unsupported"),
    ]

    for judgments, message in bad_cases:
        try:
            validate_batch_judgments(_packet(), judgments)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"{message} batch drift must fail closed")
