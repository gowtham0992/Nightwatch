from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Suite(StrEnum):
    TARGET = "target"
    REGRESSION = "regression"
    SAFETY = "safety"


class Decision(StrEnum):
    PROMOTE = "promote"
    REJECT = "reject"


class Stage(StrEnum):
    CREATED = "created"
    DIAGNOSED = "diagnosed"
    CURRICULUM_READY = "curriculum_ready"
    TRAINED = "trained"
    EVALUATED = "evaluated"
    PROMOTED = "promoted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    suite: Suite
    prompt: str
    expected_label: str
    safety_critical: bool


@dataclass(frozen=True)
class Prediction:
    case_id: str
    label: str


@dataclass(frozen=True)
class SuiteScore:
    correct: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"correct": self.correct, "total": self.total, "accuracy": self.accuracy}


@dataclass(frozen=True)
class RateMetric:
    count: int
    total: int

    @property
    def rate(self) -> float:
        return self.count / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"count": self.count, "total": self.total, "rate": self.rate}


@dataclass(frozen=True)
class EvaluationReport:
    model_id: str
    scores: dict[Suite, SuiteScore]
    label_recall: dict[Suite, dict[str, SuiteScore]]
    regression_false_page: RateMetric
    critical_misses: tuple[str, ...]
    invalid_case_ids: tuple[str, ...]

    @property
    def overall_accuracy(self) -> float:
        correct = sum(score.correct for score in self.scores.values())
        total = sum(score.total for score in self.scores.values())
        return correct / total if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "overall_accuracy": self.overall_accuracy,
            "scores": {suite.value: score.to_dict() for suite, score in self.scores.items()},
            "label_recall": {
                suite.value: {label: score.to_dict() for label, score in scores.items()}
                for suite, scores in self.label_recall.items()
            },
            "regression_false_page": self.regression_false_page.to_dict(),
            "critical_misses": list(self.critical_misses),
            "invalid_case_ids": list(self.invalid_case_ids),
        }


@dataclass(frozen=True)
class GatePolicy:
    minimum_target_gain: float = 0.2
    maximum_regression_drop: float = 0.0
    minimum_regression_non_page_recall: float = 0.5
    maximum_regression_non_page_recall_drop: float = 0.0
    require_zero_critical_misses: bool = True
    require_complete_predictions: bool = True


@dataclass(frozen=True)
class GateResult:
    decision: Decision
    reasons: tuple[str, ...]
    target_gain: float
    regression_drop: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reasons": list(self.reasons),
            "target_gain": self.target_gain,
            "regression_drop": self.regression_drop,
        }
