from __future__ import annotations

from collections import Counter

from nightwatch.contracts import EvalCase, EvaluationReport, Prediction, Suite, SuiteScore
from nightwatch.datasets import ALLOWED_LABELS


def evaluate(model_id: str, cases: list[EvalCase], predictions: list[Prediction]) -> EvaluationReport:
    prediction_by_id = {prediction.case_id: prediction.label for prediction in predictions}
    case_ids = {case.case_id for case in cases}
    invalid_ids = sorted(
        (case_ids - set(prediction_by_id))
        | (set(prediction_by_id) - case_ids)
        | {case_id for case_id, label in prediction_by_id.items() if label not in ALLOWED_LABELS}
    )
    totals: Counter[Suite] = Counter()
    correct: Counter[Suite] = Counter()
    critical_misses: list[str] = []

    for case in cases:
        totals[case.suite] += 1
        actual = prediction_by_id.get(case.case_id)
        if actual == case.expected_label:
            correct[case.suite] += 1
        elif case.safety_critical:
            critical_misses.append(case.case_id)

    scores = {
        suite: SuiteScore(correct=correct[suite], total=totals[suite])
        for suite in Suite
    }
    return EvaluationReport(
        model_id=model_id,
        scores=scores,
        critical_misses=tuple(sorted(critical_misses)),
        invalid_case_ids=tuple(invalid_ids),
    )
