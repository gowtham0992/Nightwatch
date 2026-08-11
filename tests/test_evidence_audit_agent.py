from __future__ import annotations

from nightwatch.evidence_audit_agent import (
    build_adjudication_packet,
    validate_batch_judgments,
)


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


def test_adjudication_packet_contains_only_disagreements_and_blank_decisions() -> None:
    reconciled = [
        {
            "audit_id": "audit-a",
            "source": "frozen",
            "case_id": "target-001",
            "original_suite": "target",
            "original_label": "page_now",
            "safety_critical": False,
            "machine_label": "investigate",
            "machine_rationale": "The incident lacks confirmed production customer impact.",
            "machine_ambiguous": False,
            "agreement": False,
            "adjudication_status": "pending",
        },
        {
            "audit_id": "audit-b",
            "source": "frozen",
            "case_id": "regression-001",
            "original_suite": "regression",
            "original_label": "defer",
            "safety_critical": False,
            "machine_label": "defer",
            "machine_rationale": "The staging-only event has no production impact.",
            "machine_ambiguous": False,
            "agreement": True,
            "adjudication_status": "not_required",
        },
    ]

    packet = build_adjudication_packet(_packet(), reconciled)

    assert packet == [
        {
            "audit_id": "audit-a",
            "source": "frozen",
            "case_id": "target-001",
            "original_suite": "target",
            "safety_critical": False,
            "prompt": "A confirmed production outage affects every customer.",
            "retained_label": "page_now",
            "machine_label": "investigate",
            "machine_rationale": "The incident lacks confirmed production customer impact.",
            "machine_ambiguous": False,
            "adjudicated_label": None,
            "adjudicator_rationale": None,
            "adjudicator": None,
            "adjudication_status": "pending",
        }
    ]
