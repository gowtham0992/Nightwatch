from __future__ import annotations

import pytest

from nightwatch.scam_data_agent import (
    BLOCK,
    CAUTION,
    _validated_authored_rows,
    maximum_train_eval_jaccard,
)


def _row(message: str, label: str, family: str, *, critical: bool = False) -> dict[str, object]:
    return {
        "message": message,
        "label": label,
        "threat_family": family,
        "rationale": "The message contains enough observable evidence for this disposition.",
        "safety_critical": critical,
    }


def test_authored_batch_enforces_counts_families_and_critical_policy() -> None:
    rows = [
        _row("A stranger asks for a recovery code to stop a transfer.", BLOCK, "credential", critical=True),
        _row("An unknown sender begins a vague personal conversation.", CAUTION, "unknown"),
    ]

    validated = _validated_authored_rows(
        rows,
        expected_count=2,
        expected_labels={BLOCK: 1, CAUTION: 1},
        allowed_families={"credential", "unknown"},
        expected_critical=1,
    )

    assert validated == rows


def test_authored_batch_rejects_duplicate_or_wrong_label_distribution() -> None:
    duplicate = _row("A stranger asks for a recovery code to stop a transfer.", BLOCK, "credential")
    rows = [duplicate, {**duplicate, "message": "  A STRANGER asks for a recovery code to stop a transfer.  "}]

    with pytest.raises(ValueError, match="duplicate canonical message"):
        _validated_authored_rows(
            rows,
            expected_count=2,
            expected_labels={BLOCK: 2},
            allowed_families={"credential"},
            expected_critical=0,
        )

    with pytest.raises(ValueError, match="label counts"):
        _validated_authored_rows(
            [_row("A stranger requests a private conversation without explaining why.", CAUTION, "unknown")],
            expected_count=1,
            expected_labels={BLOCK: 1, CAUTION: 0},
            allowed_families={"unknown"},
            expected_critical=0,
        )


def test_similarity_audit_identifies_the_most_similar_train_eval_pair() -> None:
    curriculum = [
        {"message": "A fake bank agent asks for the login recovery code now.", "label": BLOCK},
        {"message": "Dinner is ready at seven this evening.", "label": "routine"},
    ]
    evaluation = [
        {"message": "A bank agent asks for your login recovery code immediately."},
        {"message": "The bus arrives ten minutes late."},
    ]

    maximum = maximum_train_eval_jaccard(curriculum, evaluation)

    assert maximum["curriculum_index"] == 1
    assert maximum["evaluation_index"] == 1
    assert float(maximum["score"]) > 0.5
