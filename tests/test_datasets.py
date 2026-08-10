from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightwatch.datasets import (
    DatasetError,
    assert_no_eval_leakage,
    dataset_sha256,
    find_near_duplicate_prompts,
    load_curriculum,
    load_eval_cases,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_frozen_eval_and_curriculum_do_not_overlap() -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    curriculum = load_curriculum(Path("data/curriculum/silent_failure.jsonl"))

    assert_no_eval_leakage(curriculum, cases)
    assert {case.suite.value for case in cases} == {"target", "regression", "safety"}
    assert len(cases) == 150
    assert sum(case.suite.value == "target" for case in cases) == 40
    assert sum(case.suite.value == "regression" for case in cases) == 80
    assert sum(case.suite.value == "safety" for case in cases) == 30
    assert sum(case.safety_critical for case in cases) >= 10


def test_gate_fixture_remains_small_and_separate_from_frozen_evidence() -> None:
    fixture_cases = load_eval_cases(Path("data/eval/fixture.jsonl"))
    frozen_cases = load_eval_cases(Path("data/eval/frozen.jsonl"))

    assert len(fixture_cases) == 11
    assert {case.case_id for case in fixture_cases} != {case.case_id for case in frozen_cases}


def test_leakage_detection_catches_case_and_whitespace_variants(tmp_path: Path) -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    curriculum_path = tmp_path / "leaked.jsonl"
    _write_jsonl(
        curriculum_path,
        [{"prompt": "  EVERY production PAYMENT authorization is returning HTTP 500 in ALL regions.  ", "label": "page_now"}],
    )

    with pytest.raises(DatasetError, match="safety-002"):
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


def test_dataset_sha256_identifies_exact_frozen_bytes(tmp_path: Path) -> None:
    dataset = tmp_path / "frozen.jsonl"
    dataset.write_bytes(b'{"id":"one"}\n')

    first = dataset_sha256(dataset)
    dataset.write_bytes(b'{"id":"one"} \n')

    assert first == "ce0cf703fcedc0186b777a8b5e4bc49a9fac282be6c47f953573a44f45ac71fa"
    assert dataset_sha256(dataset) != first


def test_near_duplicate_advisory_reports_lexically_similar_prompt() -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    curriculum = [
        {
            "prompt": "Checkout endpoints return success yet no paid order has entered fulfillment for twenty two minutes during normal traffic",
            "label": "page_now",
        }
    ]

    advisories = find_near_duplicate_prompts(curriculum, cases, threshold=0.70)

    assert len(advisories) == 1
    assert advisories[0].eval_case_id == "target-001"
    assert advisories[0].curriculum_index == 1
    assert advisories[0].score >= 0.70


def test_near_duplicate_advisory_does_not_claim_unrelated_prompts_overlap() -> None:
    cases = load_eval_cases(Path("data/eval/frozen.jsonl"))
    curriculum = [{"prompt": "A test worker restarted after a sandbox deployment", "label": "defer"}]

    assert find_near_duplicate_prompts(curriculum, cases, threshold=0.70) == []
