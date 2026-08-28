from __future__ import annotations

import json
from pathlib import Path

from nightwatch.registry_probe import build_real_spike_request


def _jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_spike_projection_matches_retained_baseline_errors() -> None:
    request = build_real_spike_request()
    cases = {str(row["id"]): row for row in _jsonl("data/scam_safety/development-v0.jsonl")}
    predictions = {
        str(row["id"]): row
        for row in _jsonl(
            "artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-development-predictions.jsonl"
        )
    }

    for error in request.observed_errors:
        case = cases[error.case_id]
        prediction = predictions[error.case_id]
        assert error.text == case["message"]
        assert error.expected_label == case["expected_label"]
        assert error.predicted_label == prediction["label"]
        assert error.expected_label != error.predicted_label
