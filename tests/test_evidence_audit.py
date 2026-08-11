from __future__ import annotations

from nightwatch.contracts import EvalCase, Suite
from nightwatch.evidence_audit import build_blind_audit, reconcile_machine_judgments


def _cases(prefix: str) -> list[EvalCase]:
    return [
        EvalCase(f"{prefix}-1", Suite.SAFETY, f"{prefix} explicit outage", "page_now", True),
        EvalCase(f"{prefix}-2", Suite.REGRESSION, f"{prefix} recovered test", "defer", False),
    ]


def test_blind_audit_is_complete_deterministic_and_hides_labels() -> None:
    first = build_blind_audit({"development": _cases("dev"), "frozen": _cases("frozen")})
    second = build_blind_audit({"frozen": _cases("frozen"), "development": _cases("dev")})

    assert first == second
    assert len(first.packet) == len(first.mapping) == 4
    assert {row["prompt"] for row in first.packet} == {
        "dev explicit outage",
        "dev recovered test",
        "frozen explicit outage",
        "frozen recovered test",
    }
    assert all(set(row) == {"audit_id", "prompt"} for row in first.packet)
    assert all("dev-" not in row["audit_id"] and "frozen-" not in row["audit_id"] for row in first.packet)


def test_machine_reconciliation_requires_exactly_one_valid_judgment_per_case() -> None:
    audit = build_blind_audit({"development": _cases("dev")})
    judgments = [
        {
            "audit_id": row["audit_id"],
            "label": "page_now" if "outage" in row["prompt"] else "defer",
            "rationale": "The prompt contains enough explicit evidence to apply the written rubric.",
            "ambiguous": False,
        }
        for row in audit.packet
    ]

    reconciled = reconcile_machine_judgments(audit, judgments)

    assert len(reconciled) == 2
    assert {row["agreement"] for row in reconciled} == {True}


def test_machine_reconciliation_rejects_missing_duplicate_or_unknown_rows() -> None:
    audit = build_blind_audit({"development": _cases("dev")})
    valid = {
        "audit_id": audit.packet[0]["audit_id"],
        "label": "page_now",
        "rationale": "The prompt contains explicit production impact under the written rubric.",
        "ambiguous": False,
    }

    for judgments, message in [
        ([valid], "coverage"),
        ([valid, valid], "duplicate"),
        (
            [
                valid,
                {
                    **valid,
                    "audit_id": "unknown-audit-id",
                },
            ],
            "unknown",
        ),
    ]:
        try:
            reconcile_machine_judgments(audit, judgments)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"{message} machine judgment must fail closed")
