from pathlib import Path

from nightwatch.contracts import Decision, Prediction, Suite
from nightwatch.datasets import load_eval_cases, load_predictions
from nightwatch.evaluation import evaluate
from nightwatch.gate import decide


CASES = load_eval_cases(Path("data/eval/fixture.jsonl"))
BASELINE = evaluate("baseline", CASES, load_predictions(Path("data/predictions/baseline.jsonl")))


def test_promotes_candidate_with_target_gain_and_no_regressions() -> None:
    candidate = evaluate(
        "good",
        CASES,
        load_predictions(Path("data/predictions/good_candidate.jsonl")),
    )

    result = decide(BASELINE, candidate)

    assert result.decision is Decision.PROMOTE
    assert result.target_gain == 0.4
    assert result.regression_drop == 0.0


def test_rejects_higher_scoring_candidate_with_one_critical_miss() -> None:
    candidate = evaluate(
        "bad-high-score",
        CASES,
        load_predictions(Path("data/predictions/bad_high_score_candidate.jsonl")),
    )

    result = decide(BASELINE, candidate)

    assert candidate.overall_accuracy > BASELINE.overall_accuracy
    assert result.decision is Decision.REJECT
    assert result.reasons == ("critical safety misses: safety-01",)


def test_rejects_candidate_with_missing_prediction() -> None:
    predictions = load_predictions(Path("data/predictions/good_candidate.jsonl"))[:-1]
    candidate = evaluate("incomplete", CASES, predictions)

    result = decide(BASELINE, candidate)

    assert result.decision is Decision.REJECT
    assert "safety-02" in result.reasons[-1]


def test_rejects_candidate_with_invalid_model_output() -> None:
    predictions = load_predictions(Path("data/predictions/good_candidate.jsonl"))
    predictions[0] = type(predictions[0])(case_id="target-01", label="page now because this is urgent")
    candidate = evaluate("verbose-output", CASES, predictions)

    result = decide(BASELINE, candidate)

    assert result.decision is Decision.REJECT
    assert "target-01" in result.reasons[-1]


def test_rejects_always_page_candidate_even_when_aggregate_regression_improves() -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    baseline = evaluate(
        "always-defer-baseline",
        cases,
        [Prediction(case.case_id, "defer") for case in cases],
    )
    candidate = evaluate(
        "always-page-candidate",
        cases,
        [Prediction(case.case_id, "page_now") for case in cases],
    )

    result = decide(baseline, candidate)

    assert candidate.scores[Suite.REGRESSION].accuracy > baseline.scores[Suite.REGRESSION].accuracy
    assert candidate.critical_misses == ()
    assert result.decision is Decision.REJECT
    assert any("defer recall" in reason for reason in result.reasons)


def test_rejects_candidate_when_non_page_label_recall_declines() -> None:
    candidate_predictions = load_predictions(Path("data/predictions/good_candidate.jsonl"))
    candidate_predictions[5] = Prediction("regression-01", "page_now")
    candidate = evaluate("pager-fatigue", CASES, candidate_predictions)

    result = decide(BASELINE, candidate)

    assert result.decision is Decision.REJECT
    assert any("defer recall declined" in reason for reason in result.reasons)
