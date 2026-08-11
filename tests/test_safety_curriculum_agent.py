from __future__ import annotations

from nightwatch.safety_curriculum_agent import (
    EXPECTED_COUNTS,
    GENERATION_PLAN,
    MODEL_ID,
    _validate_generated_rows,
)


def _generated_rows() -> list[dict[str, object]]:
    return [
        {
            "prompt": f"Unique explicit operational evidence for {label} {group} example {index}",
            "label": label,
            "generation_group": group,
            "teacher_rationale": "The stated evidence crosses the fixed severity boundary for this label.",
        }
        for label, groups in GENERATION_PLAN.items()
        for group, count in groups.items()
        for index in range(count)
    ]


def test_safety_augmentation_enforces_fixed_counts_and_rationales() -> None:
    rows = _validate_generated_rows(
        _generated_rows(),
        base_curriculum=[{"prompt": "Existing base curriculum prompt", "label": "defer"}],
    )

    assert len(rows) == sum(EXPECTED_COUNTS.values()) == 32
    assert {row["teacher_model"] for row in rows} == {MODEL_ID}


def test_safety_augmentation_rejects_duplicate_base_prompt() -> None:
    rows = _generated_rows()
    rows[0]["prompt"] = "Existing base curriculum prompt"

    try:
        _validate_generated_rows(
            rows,
            base_curriculum=[{"prompt": " existing BASE curriculum prompt ", "label": "defer"}],
        )
    except ValueError as exc:
        assert "duplicate canonical prompt" in str(exc)
    else:
        raise AssertionError("base-curriculum duplication must fail closed")


def test_safety_augmentation_rejects_plan_drift() -> None:
    rows = _generated_rows()
    rows[0]["generation_group"] = "silent_downstream_stall"

    try:
        _validate_generated_rows(rows, base_curriculum=[])
    except ValueError as exc:
        assert "fixed plan" in str(exc)
    else:
        raise AssertionError("generation-plan drift must fail closed")
