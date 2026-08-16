from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightwatch.scam_gate import build_scam_gate_record


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "scam-safety"
BASELINE = ARTIFACTS / (
    "scam-v0-de1e6009-2d77e636-c0e947096d-"
    "evidence-ffca8c22-predictions.jsonl"
)

ARCHIVED_DECISIONS = (
    (
        "scam-candidate-v1-d0ab5041-ffca8c22-838eb5ca96-gate.json",
        "scam-candidate-v1-d0ab5041-ffca8c22-838eb5ca96-reevaluation-predictions.jsonl",
        "reject",
    ),
    (
        "scam-candidate-v2-2b769143-ffca8c22-0d858e40da-gate.json",
        "scam-candidate-v2-2b769143-ffca8c22-0d858e40da-reevaluation-predictions.jsonl",
        "reject",
    ),
    (
        "scam-candidate-v3-ebd8e944-ffca8c22-ae20b3fe51-gate.json",
        "scam-candidate-v3-ebd8e944-ffca8c22-ae20b3fe51-reevaluation-predictions.jsonl",
        "reject",
    ),
    (
        "scam-candidate-v5-ebd8e944-ffca8c22-2f98bfc17f-gate.json",
        "scam-candidate-v6-ebd8e944-ffca8c22-49b834a25c-development-predictions.jsonl",
        "reject",
    ),
    (
        "scam-candidate-v7-0f932496-ffca8c22-349438eaa4-gate.json",
        "scam-candidate-v7-0f932496-ffca8c22-349438eaa4-development-predictions.jsonl",
        "reject",
    ),
    (
        "scam-candidate-v8-fd2b06dd-ffca8c22-7e228df886-gate.json",
        "scam-candidate-v8-fd2b06dd-ffca8c22-7e228df886-reevaluation-predictions.jsonl",
        "promote",
    ),
)


@pytest.mark.parametrize(
    ("gate_filename", "candidate_predictions_filename", "expected_decision"),
    ARCHIVED_DECISIONS,
)
def test_archived_scam_decision_recomputes_from_committed_predictions(
    gate_filename: str,
    candidate_predictions_filename: str,
    expected_decision: str,
) -> None:
    archived = json.loads((ARTIFACTS / gate_filename).read_text(encoding="utf-8"))

    recomputed = build_scam_gate_record(
        ROOT / "data" / "scam_safety" / "mission.json",
        ROOT / "data" / "scam_safety" / "development-v1.jsonl",
        BASELINE,
        ARTIFACTS / candidate_predictions_filename,
        baseline_id=archived["baseline_id"],
        candidate_id=archived["candidate_id"],
    )

    assert recomputed["decision"]["decision"] == expected_decision
    assert recomputed == archived
