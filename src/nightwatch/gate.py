from __future__ import annotations

from nightwatch.contracts import (
    Decision,
    EvalCase,
    EvaluationReport,
    GatePolicy,
    GateResult,
    Prediction,
    Suite,
)


def decide(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    policy: GatePolicy = GatePolicy(),
) -> GateResult:
    reasons: list[str] = []
    target_gain = candidate.scores[Suite.TARGET].accuracy - baseline.scores[Suite.TARGET].accuracy
    regression_drop = baseline.scores[Suite.REGRESSION].accuracy - candidate.scores[Suite.REGRESSION].accuracy

    if target_gain + 1e-12 < policy.minimum_target_gain:
        reasons.append(
            f"target gain {target_gain:.3f} is below required {policy.minimum_target_gain:.3f}"
        )
    if regression_drop - 1e-12 > policy.maximum_regression_drop:
        reasons.append(
            f"regression drop {regression_drop:.3f} exceeds allowed {policy.maximum_regression_drop:.3f}"
        )
    for label in ("defer", "investigate"):
        baseline_recall = baseline.label_recall[Suite.REGRESSION][label].accuracy
        candidate_recall = candidate.label_recall[Suite.REGRESSION][label].accuracy
        recall_drop = baseline_recall - candidate_recall
        if candidate_recall + 1e-12 < policy.minimum_regression_non_page_recall:
            reasons.append(
                f"regression {label} recall {candidate_recall:.3f} is below required "
                f"{policy.minimum_regression_non_page_recall:.3f}"
            )
        if recall_drop - 1e-12 > policy.maximum_regression_non_page_recall_drop:
            reasons.append(
                f"regression {label} recall declined by {recall_drop:.3f}; allowed drop is "
                f"{policy.maximum_regression_non_page_recall_drop:.3f}"
            )
    if policy.require_zero_critical_misses and candidate.critical_misses:
        reasons.append(f"critical safety misses: {', '.join(candidate.critical_misses)}")
    if policy.require_complete_predictions and candidate.invalid_case_ids:
        reasons.append(f"prediction coverage mismatch: {', '.join(candidate.invalid_case_ids)}")

    decision = Decision.REJECT if reasons else Decision.PROMOTE
    if not reasons:
        reasons.append("candidate satisfied every deterministic promotion invariant")
    return GateResult(decision, tuple(reasons), target_gain, regression_drop)


def audit_constant_policies(
    baseline: EvaluationReport,
    cases: list[EvalCase],
    policy: GatePolicy = GatePolicy(),
) -> dict[str, GateResult]:
    from nightwatch.evaluation import evaluate

    results: dict[str, GateResult] = {}
    for label in ("page_now", "investigate", "defer"):
        report = evaluate(
            f"always-{label}",
            cases,
            [Prediction(case.case_id, label) for case in cases],
        )
        results[f"always_{label}"] = decide(baseline, report, policy)
    return results
