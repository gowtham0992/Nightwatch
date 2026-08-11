from __future__ import annotations

from nightwatch.contracts import EvalCase, Prediction, Suite
from nightwatch.evaluation import evaluate
from nightwatch.v0 import (
    V0_CATEGORIES,
    V0_POLICY_V2,
    assess_v0,
    balanced_category_counts,
    validate_v0_curriculum,
)


def _curriculum_rows(per_label: int = 12) -> list[dict[str, object]]:
    return [
        {
            "prompt": f"Unique operational alert {label} {category} example {index}",
            "label": label,
            "category": category,
        }
        for label in sorted(V0_CATEGORIES)
        for category, count in balanced_category_counts(label, per_label).items()
        for index in range(count)
    ]


def test_v0_curriculum_requires_balanced_code_owned_taxonomy() -> None:
    rows = _curriculum_rows()

    assert len(validate_v0_curriculum(rows, expected_per_label=12)) == 36

    rows[0]["category"] = "silent_downstream_stall"
    try:
        validate_v0_curriculum(rows, expected_per_label=12)
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("withheld category must be rejected")


def test_v0_curriculum_rejects_category_collapse_with_balanced_labels() -> None:
    rows = _curriculum_rows()
    defer_rows = [row for row in rows if row["label"] == "defer"]
    defer_rows[0]["category"] = defer_rows[-1]["category"]

    try:
        validate_v0_curriculum(rows, expected_per_label=12)
    except ValueError as exc:
        assert "category counts" in str(exc)
    else:
        raise AssertionError("category collapse must be rejected")


def test_v0_assessment_accepts_deployable_student_with_target_blind_spot() -> None:
    cases = [
        EvalCase("target", Suite.TARGET, "target prompt", "page_now", False),
        EvalCase("regression-defer", Suite.REGRESSION, "defer prompt", "defer", False),
        EvalCase(
            "regression-investigate",
            Suite.REGRESSION,
            "investigate prompt",
            "investigate",
            False,
        ),
        EvalCase("regression-page", Suite.REGRESSION, "page prompt", "page_now", False),
        EvalCase("safety-critical", Suite.SAFETY, "critical prompt", "page_now", True),
    ]
    predictions = [
        Prediction("target", "investigate"),
        Prediction("regression-defer", "defer"),
        Prediction("regression-investigate", "investigate"),
        Prediction("regression-page", "page_now"),
        Prediction("safety-critical", "page_now"),
    ]

    assessment = assess_v0(evaluate("v0", cases, predictions))

    assert assessment.accepted is True


def test_v0_assessment_rejects_unsafe_or_target_solved_student() -> None:
    cases = [
        EvalCase("target", Suite.TARGET, "target prompt", "page_now", False),
        EvalCase("regression-defer", Suite.REGRESSION, "defer prompt", "defer", False),
        EvalCase(
            "regression-investigate",
            Suite.REGRESSION,
            "investigate prompt",
            "investigate",
            False,
        ),
        EvalCase("regression-page", Suite.REGRESSION, "page prompt", "page_now", False),
        EvalCase("safety-critical", Suite.SAFETY, "critical prompt", "page_now", True),
    ]
    predictions = [
        Prediction("target", "page_now"),
        Prediction("regression-defer", "defer"),
        Prediction("regression-investigate", "investigate"),
        Prediction("regression-page", "page_now"),
        Prediction("safety-critical", "defer"),
    ]

    assessment = assess_v0(evaluate("bad-v0", cases, predictions))

    assert assessment.accepted is False
    assert any("withheld-behavior ceiling" in reason for reason in assessment.reasons)
    assert any("critical safety misses" in reason for reason in assessment.reasons)


def test_v2_policy_removes_only_the_artificial_target_ceiling() -> None:
    cases = [
        EvalCase("target", Suite.TARGET, "target prompt", "page_now", False),
        EvalCase("regression-defer", Suite.REGRESSION, "defer prompt", "defer", False),
        EvalCase(
            "regression-investigate",
            Suite.REGRESSION,
            "investigate prompt",
            "investigate",
            False,
        ),
        EvalCase("regression-page", Suite.REGRESSION, "page prompt", "page_now", False),
        EvalCase("safety-critical", Suite.SAFETY, "critical prompt", "page_now", True),
    ]
    predictions = [
        Prediction("target", "page_now"),
        Prediction("regression-defer", "defer"),
        Prediction("regression-investigate", "investigate"),
        Prediction("regression-page", "page_now"),
        Prediction("safety-critical", "page_now"),
    ]
    report = evaluate("competent-v0", cases, predictions)

    assert assess_v0(report).accepted is False
    assert assess_v0(report, policy=V0_POLICY_V2).accepted is True
