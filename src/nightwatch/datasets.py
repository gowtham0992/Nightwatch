from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from nightwatch.contracts import EvalCase, Prediction, Suite

ALLOWED_LABELS = frozenset({"page_now", "investigate", "defer"})
MAX_PROMPT_CHARS = 4_000
_WHITESPACE = re.compile(r"\s+")


class DatasetError(ValueError):
    pass


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise DatasetError(f"{path}:{line_number}: each row must be an object")
        rows.append(row)
    if not rows:
        raise DatasetError(f"{path}: dataset is empty")
    return rows


def canonical_prompt(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return _WHITESPACE.sub(" ", normalized)


def prompt_fingerprint(value: str) -> str:
    return hashlib.sha256(canonical_prompt(value).encode("utf-8")).hexdigest()


def _valid_text(value: object, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(f"{source}: {field} must be a non-empty string")
    if len(value) > MAX_PROMPT_CHARS:
        raise DatasetError(f"{source}: {field} exceeds {MAX_PROMPT_CHARS} characters")
    return value


def load_eval_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    seen_prompts: set[str] = set()
    for index, row in enumerate(_read_jsonl(path), start=1):
        source = f"{path}:{index}"
        case_id = _valid_text(row.get("id"), "id", source)
        prompt = _valid_text(row.get("prompt"), "prompt", source)
        label = _valid_text(row.get("expected_label"), "expected_label", source)
        if case_id in seen_ids:
            raise DatasetError(f"{source}: duplicate id {case_id!r}")
        fingerprint = prompt_fingerprint(prompt)
        if fingerprint in seen_prompts:
            raise DatasetError(f"{source}: duplicate canonical prompt")
        try:
            suite = Suite(row.get("suite"))
        except (TypeError, ValueError) as exc:
            raise DatasetError(f"{source}: suite must be target, regression, or safety") from exc
        if label not in ALLOWED_LABELS:
            raise DatasetError(f"{source}: unsupported expected_label {label!r}")
        critical = row.get("safety_critical", False)
        if not isinstance(critical, bool):
            raise DatasetError(f"{source}: safety_critical must be boolean")
        if critical and suite is not Suite.SAFETY:
            raise DatasetError(f"{source}: safety_critical cases must belong to safety suite")
        cases.append(EvalCase(case_id, suite, prompt, label, critical))
        seen_ids.add(case_id)
        seen_prompts.add(fingerprint)
    missing_suites = set(Suite) - {case.suite for case in cases}
    if missing_suites:
        raise DatasetError(f"{path}: missing suites: {sorted(suite.value for suite in missing_suites)}")
    return cases


def load_predictions(path: Path) -> list[Prediction]:
    predictions: list[Prediction] = []
    seen_ids: set[str] = set()
    for index, row in enumerate(_read_jsonl(path), start=1):
        source = f"{path}:{index}"
        case_id = _valid_text(row.get("id"), "id", source)
        label = _valid_text(row.get("label"), "label", source)
        if case_id in seen_ids:
            raise DatasetError(f"{source}: duplicate prediction id {case_id!r}")
        predictions.append(Prediction(case_id, label))
        seen_ids.add(case_id)
    return predictions


def load_curriculum(path: Path) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    seen_prompts: set[str] = set()
    for index, row in enumerate(_read_jsonl(path), start=1):
        source = f"{path}:{index}"
        prompt = _valid_text(row.get("prompt"), "prompt", source)
        label = _valid_text(row.get("label"), "label", source)
        if label not in ALLOWED_LABELS:
            raise DatasetError(f"{source}: unsupported label {label!r}")
        fingerprint = prompt_fingerprint(prompt)
        if fingerprint in seen_prompts:
            raise DatasetError(f"{source}: duplicate canonical prompt")
        examples.append({"prompt": prompt, "label": label})
        seen_prompts.add(fingerprint)
    return examples


def assert_no_eval_leakage(curriculum: list[dict[str, str]], eval_cases: list[EvalCase]) -> None:
    training_fingerprints = {prompt_fingerprint(row["prompt"]) for row in curriculum}
    leaked_ids = [case.case_id for case in eval_cases if prompt_fingerprint(case.prompt) in training_fingerprints]
    if leaked_ids:
        raise DatasetError(f"curriculum contains frozen eval prompts: {', '.join(sorted(leaked_ids))}")
