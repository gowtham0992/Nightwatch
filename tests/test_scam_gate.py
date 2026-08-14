from pathlib import Path

import pytest

from nightwatch.scam_gate import build_scam_gate_record


def test_real_candidate_is_refused_by_the_frozen_gate() -> None:
    record = build_scam_gate_record(
        Path("data/scam_safety/mission.json"),
        Path("data/scam_safety/development-v1.jsonl"),
        Path(
            "artifacts/scam-safety/"
            "scam-v0-de1e6009-2d77e636-c0e947096d-evidence-ffca8c22-predictions.jsonl"
        ),
        Path(
            "artifacts/scam-safety/"
            "scam-candidate-v1-d0ab5041-ffca8c22-838eb5ca96-development-predictions.jsonl"
        ),
        baseline_id="scam-v0-de1e6009-2d77e636-c0e947096d",
        candidate_id="scam-candidate-v1-d0ab5041-ffca8c22-838eb5ca96",
    )

    assert record["decision"]["decision"] == "reject"
    assert record["decision"]["target_gain"] == pytest.approx(5 / 36)
    assert any("target gain" in reason for reason in record["decision"]["reasons"])
    assert any("safety block recall" in reason for reason in record["decision"]["reasons"])
