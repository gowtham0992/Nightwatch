from pathlib import Path

from nightwatch.contracts import Prediction, Suite
from nightwatch.datasets import load_eval_cases
from nightwatch.evaluation import evaluate


def test_evaluation_reports_per_label_recall_and_false_page_rate() -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    predictions = [Prediction(case.case_id, "page_now") for case in cases]

    report = evaluate("always-page", cases, predictions)

    assert report.label_recall[Suite.REGRESSION]["page_now"].accuracy == 1.0
    assert report.label_recall[Suite.REGRESSION]["investigate"].accuracy == 0.0
    assert report.label_recall[Suite.REGRESSION]["defer"].accuracy == 0.0
    assert report.regression_false_page.count == 50
    assert report.regression_false_page.total == 50
    assert report.regression_false_page.rate == 1.0


def test_evaluation_false_page_rate_uses_only_non_page_regression_cases() -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    predictions = [Prediction(case.case_id, case.expected_label) for case in cases]
    predictions[40] = Prediction("regression-001", "page_now")

    report = evaluate("one-false-page", cases, predictions)

    assert report.regression_false_page.count == 1
    assert report.regression_false_page.total == 50
    assert report.regression_false_page.rate == 0.02
