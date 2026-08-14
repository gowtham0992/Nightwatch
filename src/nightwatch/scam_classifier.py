from __future__ import annotations

from collections.abc import Callable, Sequence

from nightwatch.scam_safety import SCAM_LABELS, ScamMission


SCAM_LABEL_TO_ID = {label: index for index, label in enumerate(SCAM_LABELS)}
SCAM_ID_TO_LABEL = {index: label for label, index in SCAM_LABEL_TO_ID.items()}
SCAM_CLASSIFIER_PIPELINE_VERSION = 3
SCAM_EVALUATION_BATCH_SIZE = 1


def initialize_scam_training_seed(
    seed: int,
    set_seed: Callable[..., None],
) -> None:
    """Seed every supported runtime before newly initialized model weights exist."""
    set_seed(seed, deterministic=True)


def scam_classification_metrics(
    expected: Sequence[int],
    predicted: Sequence[int],
) -> dict[str, float]:
    if len(expected) != len(predicted) or not expected:
        raise ValueError("expected and predicted must be non-empty sequences of equal length")
    if any(value not in SCAM_ID_TO_LABEL for value in (*expected, *predicted)):
        raise ValueError("classification metrics received an unsupported label id")

    accuracy = sum(
        actual == guess for actual, guess in zip(expected, predicted, strict=True)
    ) / len(expected)
    f1_scores: list[float] = []
    for label_id in SCAM_ID_TO_LABEL:
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


def scam_classifier_text(message: str, mission: ScamMission) -> str:
    return f"{mission.instruction}\n\nMessage:\n{message.strip()}"
