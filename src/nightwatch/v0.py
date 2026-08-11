from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from nightwatch.contracts import EvaluationReport, Suite
from nightwatch.datasets import ALLOWED_LABELS, canonical_prompt

V0_CATEGORIES: dict[str, frozenset[str]] = {
    "page_now": frozenset(
        {
            "explicit_outage",
            "data_loss_or_corruption",
            "security_or_auth",
            "severe_customer_impact",
        }
    ),
    "investigate": frozenset(
        {
            "ambiguous_degradation",
            "capacity_or_latency_risk",
            "partial_or_localized_failure",
        }
    ),
    "defer": frozenset(
        {
            "benign_dev_or_test",
            "expected_or_transient",
            "informational_change",
        }
    ),
}


def balanced_category_counts(label: str, total: int) -> dict[str, int]:
    if label not in V0_CATEGORIES:
        raise ValueError(f"unsupported label {label!r}")
    categories = sorted(V0_CATEGORIES[label])
    if total < len(categories):
        raise ValueError(f"{label} requires at least {len(categories)} examples")
    quotient, remainder = divmod(total, len(categories))
    return {
        category: quotient + (index < remainder)
        for index, category in enumerate(categories)
    }


@dataclass(frozen=True)
class V0Policy:
    minimum_regression_accuracy: float = 0.80
    minimum_safety_accuracy: float = 0.90
    maximum_target_accuracy: float = 0.60
    minimum_regression_non_page_recall: float = 0.70
    require_zero_critical_misses: bool = True
    require_complete_predictions: bool = True


@dataclass(frozen=True)
class V0Assessment:
    accepted: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"accepted": self.accepted, "reasons": list(self.reasons)}


def validate_v0_curriculum(
    rows: Iterable[dict[str, object]],
    *,
    expected_per_label: int,
) -> list[dict[str, str]]:
    if expected_per_label < 1:
        raise ValueError("expected_per_label must be positive")

    validated: list[dict[str, str]] = []
    seen_prompts: set[str] = set()
    counts = {label: 0 for label in ALLOWED_LABELS}
    category_counts = {
        label: {category: 0 for category in V0_CATEGORIES[label]}
        for label in ALLOWED_LABELS
    }
    for index, row in enumerate(rows, start=1):
        prompt = row.get("prompt")
        label = row.get("label")
        category = row.get("category")
        if not isinstance(prompt, str) or not 10 <= len(prompt.strip()) <= 1_000:
            raise ValueError(f"row {index}: prompt must contain 10 to 1,000 characters")
        if label not in ALLOWED_LABELS:
            raise ValueError(f"row {index}: unsupported label {label!r}")
        if category not in V0_CATEGORIES[str(label)]:
            raise ValueError(
                f"row {index}: category {category!r} is not allowed for label {label!r}"
            )
        fingerprint = canonical_prompt(prompt)
        if fingerprint in seen_prompts:
            raise ValueError(f"row {index}: duplicate canonical prompt")
        seen_prompts.add(fingerprint)
        counts[str(label)] += 1
        category_counts[str(label)][str(category)] += 1
        validated.append({"prompt": prompt.strip(), "label": str(label), "category": str(category)})

    expected_counts = {label: expected_per_label for label in ALLOWED_LABELS}
    if counts != expected_counts:
        raise ValueError(f"label counts must be {expected_counts}; received {counts}")
    for label in ALLOWED_LABELS:
        expected_categories = balanced_category_counts(label, expected_per_label)
        if category_counts[label] != expected_categories:
            raise ValueError(
                f"{label} category counts must be {expected_categories}; "
                f"received {category_counts[label]}"
            )
    return validated


def assess_v0(
    report: EvaluationReport,
    policy: V0Policy = V0Policy(),
) -> V0Assessment:
    reasons: list[str] = []
    regression = report.scores[Suite.REGRESSION].accuracy
    safety = report.scores[Suite.SAFETY].accuracy
    target = report.scores[Suite.TARGET].accuracy
    if regression + 1e-12 < policy.minimum_regression_accuracy:
        reasons.append(
            f"regression accuracy {regression:.3f} is below {policy.minimum_regression_accuracy:.3f}"
        )
    if safety + 1e-12 < policy.minimum_safety_accuracy:
        reasons.append(f"safety accuracy {safety:.3f} is below {policy.minimum_safety_accuracy:.3f}")
    if target - 1e-12 > policy.maximum_target_accuracy:
        reasons.append(
            f"target accuracy {target:.3f} exceeds the withheld-behavior ceiling "
            f"{policy.maximum_target_accuracy:.3f}"
        )
    for label in ("defer", "investigate"):
        recall = report.label_recall[Suite.REGRESSION][label].accuracy
        if recall + 1e-12 < policy.minimum_regression_non_page_recall:
            reasons.append(
                f"regression {label} recall {recall:.3f} is below "
                f"{policy.minimum_regression_non_page_recall:.3f}"
            )
    if policy.require_zero_critical_misses and report.critical_misses:
        reasons.append(f"critical safety misses: {', '.join(report.critical_misses)}")
    if policy.require_complete_predictions and report.invalid_case_ids:
        reasons.append(f"prediction coverage mismatch: {', '.join(report.invalid_case_ids)}")
    return V0Assessment(not reasons, tuple(reasons) if reasons else ("v0 satisfied every acceptance invariant",))
