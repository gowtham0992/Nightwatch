from __future__ import annotations

import pytest

from nightwatch.model_config import (
    GEMMA_1B_MODEL_ID,
    GEMMA_1B_MODEL_REVISION,
    GEMMA_MODEL_ID,
    GEMMA_MODEL_REVISION,
    validate_gemma_checkpoint,
)


@pytest.mark.parametrize(
    ("model_id", "revision"),
    [
        (GEMMA_MODEL_ID, GEMMA_MODEL_REVISION),
        (GEMMA_1B_MODEL_ID, GEMMA_1B_MODEL_REVISION),
    ],
)
def test_gemma_checkpoint_allowlist_accepts_only_pinned_models(
    model_id: str,
    revision: str,
) -> None:
    validate_gemma_checkpoint(model_id, revision)


@pytest.mark.parametrize(
    ("model_id", "revision"),
    [
        ("google/gemma-3-4b-it", "unknown"),
        (GEMMA_1B_MODEL_ID, "main"),
    ],
)
def test_gemma_checkpoint_allowlist_rejects_unpinned_models(
    model_id: str,
    revision: str,
) -> None:
    with pytest.raises(ValueError, match="immutable Nightwatch allowlist"):
        validate_gemma_checkpoint(model_id, revision)
