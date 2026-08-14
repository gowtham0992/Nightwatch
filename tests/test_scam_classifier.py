from __future__ import annotations

from pathlib import Path
import json

import pytest

from nightwatch.scam_classifier import (
    SCAM_ID_TO_LABEL,
    SCAM_LABEL_TO_ID,
    SCAM_CLASSIFIER_PIPELINE_VERSION,
    SCAM_EVALUATION_BATCH_SIZE,
    initialize_scam_training_seed,
    scam_classification_metrics,
    scam_classifier_text,
)
from nightwatch.scam_safety import BLOCK, CAUTION, ROUTINE, VERIFY, load_scam_mission
from nightwatch.predict_scam_classifier import (
    _validate_adapter_manifest,
    _validate_prediction_batch_size,
)


def test_scam_classifier_uses_the_mission_label_order() -> None:
    assert SCAM_LABEL_TO_ID == {BLOCK: 0, CAUTION: 1, VERIFY: 2, ROUTINE: 3}
    assert SCAM_ID_TO_LABEL == {0: BLOCK, 1: CAUTION, 2: VERIFY, 3: ROUTINE}


def test_scam_classifier_uses_padding_free_evaluation_after_batching_regression() -> None:
    assert SCAM_CLASSIFIER_PIPELINE_VERSION == 3
    assert SCAM_EVALUATION_BATCH_SIZE == 1


def test_training_pipeline_seeds_new_model_weights_deterministically() -> None:
    calls: list[tuple[int, bool]] = []

    initialize_scam_training_seed(
        20260813,
        lambda seed, *, deterministic: calls.append((seed, deterministic)),
    )

    assert calls == [(20260813, True)]


def test_scam_classifier_text_uses_the_pinned_instruction_and_preserves_message() -> None:
    mission = load_scam_mission(Path("data/scam_safety/mission.json"))

    rendered = scam_classifier_text("  Dinner is at seven.  ", mission)

    assert rendered.startswith(mission.instruction)
    assert rendered.endswith("Message:\nDinner is at seven.")


def test_scam_metrics_include_every_class_in_macro_f1() -> None:
    expected = [
        SCAM_LABEL_TO_ID[BLOCK],
        SCAM_LABEL_TO_ID[CAUTION],
        SCAM_LABEL_TO_ID[VERIFY],
        SCAM_LABEL_TO_ID[ROUTINE],
    ]
    predicted = [
        SCAM_LABEL_TO_ID[BLOCK],
        SCAM_LABEL_TO_ID[BLOCK],
        SCAM_LABEL_TO_ID[VERIFY],
        SCAM_LABEL_TO_ID[VERIFY],
    ]

    metrics = scam_classification_metrics(expected, predicted)

    assert metrics["accuracy"] == 0.5
    assert metrics["macro_f1"] == pytest.approx((2 / 3 + 0 + 2 / 3 + 0) / 4)


def test_scam_metrics_reject_empty_misaligned_or_unknown_ids() -> None:
    with pytest.raises(ValueError, match="equal length"):
        scam_classification_metrics([], [])
    with pytest.raises(ValueError, match="equal length"):
        scam_classification_metrics([0], [])
    with pytest.raises(ValueError, match="unsupported"):
        scam_classification_metrics([0], [99])


def test_adapter_manifest_must_match_the_mission_identity(tmp_path: Path) -> None:
    mission = load_scam_mission(Path("data/scam_safety/mission.json"))
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    manifest = {
        "mission_id": mission.mission_id,
        "model_id": mission.model_id,
        "model_revision": mission.model_revision,
        "labels": SCAM_LABEL_TO_ID,
        "pipeline_version": SCAM_CLASSIFIER_PIPELINE_VERSION,
    }
    (adapter / "nightwatch-scam-training.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    _validate_adapter_manifest(
        adapter,
        mission.mission_id,
        mission.model_id,
        mission.model_revision,
    )

    manifest["model_revision"] = "mutable-or-wrong"
    (adapter / "nightwatch-scam-training.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match"):
        _validate_adapter_manifest(
            adapter,
            mission.mission_id,
            mission.model_id,
            mission.model_revision,
        )


@pytest.mark.parametrize("batch_size", [1, 16, 32, 64])
def test_prediction_batch_size_accepts_bounded_values(batch_size: int) -> None:
    assert _validate_prediction_batch_size(batch_size) == batch_size


@pytest.mark.parametrize("batch_size", [0, -1, 65])
def test_prediction_batch_size_rejects_unbounded_values(batch_size: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 64"):
        _validate_prediction_batch_size(batch_size)
