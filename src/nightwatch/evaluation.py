from __future__ import annotations

from collections import Counter

from nightwatch.contracts import EvalCase, EvaluationReport, Prediction, RateMetric, Suite, SuiteScore
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
    label_totals: Counter[tuple[Suite, str]] = Counter()
    label_correct: Counter[tuple[Suite, str]] = Counter()
    critical_misses: list[str] = []
    regression_false_page_count = 0
    regression_non_page_total = 0

    for case in cases:
        totals[case.suite] += 1
        label_totals[(case.suite, case.expected_label)] += 1
        actual = prediction_by_id.get(case.case_id)
        if actual == case.expected_label:
            correct[case.suite] += 1
            label_correct[(case.suite, case.expected_label)] += 1
        elif case.safety_critical:
            critical_misses.append(case.case_id)
        if case.suite is Suite.REGRESSION and case.expected_label != "page_now":
            regression_non_page_total += 1
            if actual == "page_now":
                regression_false_page_count += 1

    scores = {
        suite: SuiteScore(correct=correct[suite], total=totals[suite])
        for suite in Suite
    }
    label_recall = {
        suite: {
            label: SuiteScore(
                correct=label_correct[(suite, label)],
                total=label_totals[(suite, label)],
            )
            for label in sorted(ALLOWED_LABELS)
        }
        for suite in Suite
    }
    return EvaluationReport(
        model_id=model_id,
        scores=scores,
        label_recall=label_recall,
        regression_false_page=RateMetric(
            count=regression_false_page_count,
            total=regression_non_page_total,
        ),
        critical_misses=tuple(sorted(critical_misses)),
        invalid_case_ids=tuple(invalid_ids),
    )
