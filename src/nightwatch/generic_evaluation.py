from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from nightwatch.contracts import Suite
from nightwatch.journal import JournalError
from nightwatch.operator_contracts import FrozenDataset, MissionContract


@dataclass(frozen=True)
class GenericPrediction:
    case_id: str
    label: str
    confidence: float


def validate_predictions(
    raw: object, contract: MissionContract, dataset: FrozenDataset
) -> tuple[GenericPrediction, ...]:
    if not isinstance(raw, list):
        raise JournalError("classifier predictions must be a list")
    allowed = set(contract.labels)
    expected_ids = {str(row[contract.mapping.id_column]).strip() for row in dataset.rows}
    predictions: list[GenericPrediction] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, dict) or set(value) != {"id", "label", "confidence"}:
            raise JournalError("classifier prediction does not match the frozen schema")
        case_id = value["id"]
        label = value["label"]
        confidence = value["confidence"]
        if (
            not isinstance(case_id, str)
            or case_id not in expected_ids
            or case_id in seen
            or label not in allowed
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            raise JournalError("classifier prediction violates the frozen contract")
        seen.add(case_id)
        predictions.append(GenericPrediction(case_id, label, float(confidence)))
    if seen != expected_ids:
        raise JournalError("classifier predictions are incomplete")
    return tuple(predictions)


def evaluate_predictions(
    artifact_name: str,
    predictions: tuple[GenericPrediction, ...],
    contract: MissionContract,
    dataset: FrozenDataset,
) -> dict[str, Any]:
    by_id = {prediction.case_id: prediction for prediction in predictions}
    totals: dict[str, int] = defaultdict(int)
    correct: dict[str, int] = defaultdict(int)
    label_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    label_correct: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    errors: list[dict[str, Any]] = []
    critical_misses: list[str] = []
    for row in dataset.rows:
        case_id = str(row[contract.mapping.id_column]).strip()
        expected = str(row[contract.mapping.label_column]).strip()
        suite = Suite(str(row[contract.mapping.suite_column]).strip())
        predicted = by_id[case_id]
        totals[suite.value] += 1
        label_totals[suite.value][expected] += 1
        if predicted.label == expected:
            correct[suite.value] += 1
            label_correct[suite.value][expected] += 1
            continue
        critical = False
        if contract.mapping.safety_critical_column:
            critical = str(row[contract.mapping.safety_critical_column]).strip().lower() == "true"
        if critical:
            critical_misses.append(case_id)
        errors.append(
            {
                "case_id": case_id,
                "suite": suite.value,
                "text": str(row[contract.mapping.text_column]),
                "expected_label": expected,
                "predicted_label": predicted.label,
                "confidence": predicted.confidence,
                "safety_critical": critical,
            }
        )
    scores = {
        suite.value: {
            "correct": correct[suite.value],
            "total": totals[suite.value],
            "accuracy": correct[suite.value] / totals[suite.value],
        }
        for suite in Suite
    }
    label_recall = {
        suite: {
            label: {
                "correct": label_correct[suite][label],
                "total": count,
                "accuracy": label_correct[suite][label] / count,
            }
            for label, count in totals_by_label.items()
        }
        for suite, totals_by_label in label_totals.items()
    }
    return {
        "artifact_name": artifact_name,
        "scores": scores,
        "label_recall": label_recall,
        "error_count": len(errors),
        "errors": errors,
        "critical_miss_count": len(critical_misses),
        "critical_misses": critical_misses,
    }


def decide_release(
    baseline: dict[str, Any], candidate: dict[str, Any], contract: MissionContract
) -> dict[str, Any]:
    target_gain = candidate["scores"]["target"]["accuracy"] - baseline["scores"]["target"]["accuracy"]
    regression_drop = baseline["scores"]["regression"]["accuracy"] - candidate["scores"]["regression"]["accuracy"]
    safety_accuracy = candidate["scores"]["safety"]["accuracy"]
    failed: list[str] = []
    if target_gain < contract.policy.minimum_target_gain:
        failed.append("minimum_target_gain")
    if regression_drop > contract.policy.maximum_regression_drop:
        failed.append("maximum_regression_drop")
    if safety_accuracy < contract.policy.minimum_safety_accuracy:
        failed.append("minimum_safety_accuracy")
    if contract.policy.require_zero_critical_misses and candidate["critical_miss_count"] != 0:
        failed.append("require_zero_critical_misses")
    return {
        "decision": "promote" if not failed else "refuse",
        "accepted": not failed,
        "failed_invariants": failed,
        "observed": {
            "target_gain": target_gain,
            "regression_drop": regression_drop,
            "safety_accuracy": safety_accuracy,
            "critical_miss_count": candidate["critical_miss_count"],
        },
        "policy": {
            "minimum_target_gain": contract.policy.minimum_target_gain,
            "maximum_regression_drop": contract.policy.maximum_regression_drop,
            "minimum_safety_accuracy": contract.policy.minimum_safety_accuracy,
            "require_zero_critical_misses": contract.policy.require_zero_critical_misses,
        },
        "authority": "deterministic_code_only",
    }
