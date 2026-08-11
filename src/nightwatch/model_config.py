GEMMA_MODEL_ID = "google/gemma-3-270m-it"
GEMMA_MODEL_REVISION = "ac82b4e820549b854eebf28ce6dedaf9fdfa17b3"
GEMMA_1B_MODEL_ID = "google/gemma-3-1b-it"
GEMMA_1B_MODEL_REVISION = "dcc83ea841ab6100d6b47a070329e1ba4cf78752"

ALLOWED_GEMMA_CHECKPOINTS = {
    GEMMA_MODEL_ID: GEMMA_MODEL_REVISION,
    GEMMA_1B_MODEL_ID: GEMMA_1B_MODEL_REVISION,
}


def validate_gemma_checkpoint(model_id: str, model_revision: str) -> None:
    expected_revision = ALLOWED_GEMMA_CHECKPOINTS.get(model_id)
    if expected_revision is None or model_revision != expected_revision:
        raise ValueError("model checkpoint is not in the immutable Nightwatch allowlist")
