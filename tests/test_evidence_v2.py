from __future__ import annotations

from nightwatch.evidence_v2 import (
    apply_adjudicated_labels,
    validate_adjudication_decisions,
)


def _packet() -> list[dict[str, object]]:
    return [
        {
            "audit_id": "audit-a",
            "source": "development",
            "case_id": "dev-target-001",
            "original_suite": "target",
            "safety_critical": False,
            "prompt": "A production output is missing after its deadline.",
            "retained_label": "page_now",
            "machine_label": "investigate",
            "machine_rationale": "Missing output without confirmed customer impact requires investigation.",
            "machine_ambiguous": False,
            "adjudicated_label": None,
            "adjudicator_rationale": None,
            "adjudicator": None,
            "adjudication_status": "pending",
        }
    ]


def _decisions() -> list[dict[str, object]]:
    return [
        {
            **_packet()[0],
            "adjudicated_label": "investigate",
            "adjudicator_rationale": (
                "The prompt confirms missing output but does not establish a customer-flow halt."
            ),
            "adjudicator": "independent-reviewer",
            "adjudication_status": "resolved",
        }
    ]


def test_adjudication_validation_requires_exact_coverage_and_immutable_context() -> None:
    validated = validate_adjudication_decisions(_packet(), _decisions())

    assert validated["audit-a"]["adjudicated_label"] == "investigate"

    for decisions, message in [
        ([], "coverage"),
        ([_decisions()[0], _decisions()[0]], "coverage"),
        ([{**_decisions()[0], "prompt": "Changed incident text"}], "context drift"),
        ([{**_decisions()[0], "adjudication_status": "pending"}], "resolved"),
        ([{**_decisions()[0], "adjudicated_label": "wake_someone"}], "unsupported"),
    ]:
        try:
            validate_adjudication_decisions(_packet(), decisions)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"{message} must fail closed")


def test_apply_adjudicated_labels_changes_only_expected_label() -> None:
    development = [
        {
            "id": "dev-target-001",
            "suite": "target",
            "prompt": "A production output is missing after its deadline.",
            "expected_label": "page_now",
            "safety_critical": False,
        },
        {
            "id": "dev-regression-001",
            "suite": "regression",
            "prompt": "A staging warning recovered automatically.",
            "expected_label": "defer",
            "safety_critical": False,
        },
    ]
    mapping = [
        {
            "audit_id": "audit-a",
            "source": "development",
            "case_id": "dev-target-001",
            "original_suite": "target",
            "original_label": "page_now",
            "safety_critical": False,
        },
        {
            "audit_id": "audit-b",
            "source": "development",
            "case_id": "dev-regression-001",
            "original_suite": "regression",
            "original_label": "defer",
            "safety_critical": False,
        },
    ]

    released = apply_adjudicated_labels(
        {"development": development},
        mapping,
        validate_adjudication_decisions(_packet(), _decisions()),
    )

    assert released["development"][0] == {
        **development[0],
        "expected_label": "investigate",
    }
    assert released["development"][1] == development[1]
