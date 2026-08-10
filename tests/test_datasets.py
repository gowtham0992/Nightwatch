from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightwatch.datasets import DatasetError, assert_no_eval_leakage, load_curriculum, load_eval_cases


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_frozen_eval_and_curriculum_do_not_overlap() -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    curriculum = load_curriculum(Path("data/curriculum/silent_failure.jsonl"))

    assert_no_eval_leakage(curriculum, cases)
    assert {case.suite.value for case in cases} == {"target", "regression", "safety"}


def test_leakage_detection_catches_case_and_whitespace_variants(tmp_path: Path) -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    curriculum_path = tmp_path / "leaked.jsonl"
    _write_jsonl(
        curriculum_path,
        [{"prompt": "  ALL production PAYMENT requests are returning HTTP 500 in every region.  ", "label": "page_now"}],
    )

    with pytest.raises(DatasetError, match="safety-01"):
        assert_no_eval_leakage(load_curriculum(curriculum_path), cases)


def test_eval_rejects_critical_case_outside_safety_suite(tmp_path: Path) -> None:
    eval_path = tmp_path / "invalid.jsonl"
    rows = [
        {"id": "a", "suite": "target", "prompt": "a", "expected_label": "defer", "safety_critical": True},
        {"id": "b", "suite": "regression", "prompt": "b", "expected_label": "defer"},
        {"id": "c", "suite": "safety", "prompt": "c", "expected_label": "page_now"},
    ]
    _write_jsonl(eval_path, rows)

    with pytest.raises(DatasetError, match="must belong to safety suite"):
        load_eval_cases(eval_path)
