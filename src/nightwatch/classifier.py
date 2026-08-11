from __future__ import annotations

import re
from collections.abc import Sequence

CLASSIFIER_LABELS = ("defer", "investigate", "page_now")
LABEL_TO_ID = {label: index for index, label in enumerate(CLASSIFIER_LABELS)}
ID_TO_LABEL = {index: label for label, index in LABEL_TO_ID.items()}
CLASSIFIER_PIPELINE_VERSION = 2
_PRESENTATION_PREFIX = re.compile(r"^(?:ALERT|INFO):\s*", flags=re.IGNORECASE)


def classification_metrics(expected: Sequence[int], predicted: Sequence[int]) -> dict[str, float]:
    if len(expected) != len(predicted) or not expected:
        raise ValueError("expected and predicted must be non-empty sequences of equal length")
    if any(value not in ID_TO_LABEL for value in (*expected, *predicted)):
        raise ValueError("classification metrics received an unsupported label id")

    accuracy = sum(left == right for left, right in zip(expected, predicted, strict=True)) / len(expected)
    f1_scores: list[float] = []
    for label_id in ID_TO_LABEL:
        true_positive = sum(
            actual == label_id and guess == label_id
            for actual, guess in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            actual != label_id and guess == label_id
            for actual, guess in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            actual == label_id and guess != label_id
            for actual, guess in zip(expected, predicted, strict=True)
        )
        denominator = 2 * true_positive + false_positive + false_negative
        f1_scores.append(2 * true_positive / denominator if denominator else 0.0)
    return {"accuracy": accuracy, "macro_f1": sum(f1_scores) / len(f1_scores)}


def classifier_text(prompt: str) -> str:
    normalized = _PRESENTATION_PREFIX.sub("", prompt.strip())
    return (
        "Classify this production alert as page_now, investigate, or defer.\n\n"
        f"Alert: {normalized}"
    )
