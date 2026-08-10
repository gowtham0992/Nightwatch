from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nightwatch.contracts import EvalCase, Prediction, Suite

ALLOWED_LABELS = frozenset({"page_now", "investigate", "defer"})
MAX_PROMPT_CHARS = 4_000
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class NearDuplicateAdvisory:
    curriculum_index: int
    eval_case_id: str
    score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "curriculum_index": self.curriculum_index,
            "eval_case_id": self.eval_case_id,
            "token_jaccard": round(self.score, 6),
        }


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


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prompt_tokens(value: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(canonical_prompt(value)))


def find_near_duplicate_prompts(
    curriculum: list[dict[str, str]],
    eval_cases: list[EvalCase],
    *,
    threshold: float = 0.75,
) -> list[NearDuplicateAdvisory]:
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be greater than 0 and at most 1")

    eval_tokens = [(case.case_id, _prompt_tokens(case.prompt)) for case in eval_cases]
    advisories: list[NearDuplicateAdvisory] = []
    for curriculum_index, row in enumerate(curriculum, start=1):
        training_tokens = _prompt_tokens(row["prompt"])
        for case_id, frozen_tokens in eval_tokens:
            union = training_tokens | frozen_tokens
            score = len(training_tokens & frozen_tokens) / len(union) if union else 1.0
            if score >= threshold:
                advisories.append(NearDuplicateAdvisory(curriculum_index, case_id, score))

    return sorted(
        advisories,
        key=lambda advisory: (-advisory.score, advisory.curriculum_index, advisory.eval_case_id),
    )


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
