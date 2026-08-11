from __future__ import annotations

import pytest

from nightwatch.classifier import LABEL_TO_ID, classification_metrics, classifier_text
from nightwatch.train_classifier import audit_trainable_parameters


class FakeParameter:
    def __init__(self, size: int, *, requires_grad: bool = True) -> None:
        self.size = size
        self.requires_grad = requires_grad

    def numel(self) -> int:
        return self.size


def test_classifier_metrics_report_macro_f1_without_hiding_missing_class() -> None:
    expected = [LABEL_TO_ID["defer"], LABEL_TO_ID["investigate"], LABEL_TO_ID["page_now"]]
    predicted = [LABEL_TO_ID["investigate"], LABEL_TO_ID["investigate"], LABEL_TO_ID["page_now"]]

    metrics = classification_metrics(expected, predicted)

    assert metrics["accuracy"] == pytest.approx(2 / 3)
    assert metrics["macro_f1"] == pytest.approx((0 + 2 / 3 + 1) / 3)


def test_classifier_metrics_reject_invalid_or_misaligned_inputs() -> None:
    with pytest.raises(ValueError, match="equal length"):
        classification_metrics([0], [])
    with pytest.raises(ValueError, match="unsupported"):
        classification_metrics([0], [99])


def test_classifier_text_is_stable_and_does_not_include_an_answer() -> None:
    rendered = classifier_text("  One worker restarted after a deploy.  ")

    assert rendered.endswith("Alert: One worker restarted after a deploy.")
    assert rendered.count("page_now") == 1


@pytest.mark.parametrize("prefix", ["ALERT: ", "INFO: ", "alert: ", "info:"])
def test_classifier_text_removes_label_leaking_presentation_prefix(prefix: str) -> None:
    assert classifier_text(f"{prefix}Scheduled maintenance completed.").endswith(
        "Alert: Scheduled maintenance completed."
    )


def test_trainable_parameter_audit_requires_and_counts_adapter_and_head() -> None:
    audit = audit_trainable_parameters(
        [
            ("base.weight", FakeParameter(100, requires_grad=False)),
            ("model.q_proj.lora_A.default.weight", FakeParameter(12)),
            ("model.score.modules_to_save.default.weight", FakeParameter(9)),
        ]
    )

    assert audit["total"] == 21
    assert audit["lora"] == 12
    assert audit["score_head"] == 9


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ([('model.score.weight', FakeParameter(9))], "LoRA"),
        ([('model.q_proj.lora_A.weight', FakeParameter(12))], "score head"),
    ],
)
def test_trainable_parameter_audit_fails_closed_when_component_is_frozen(
    parameters: list[tuple[str, FakeParameter]], message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        audit_trainable_parameters(parameters)
