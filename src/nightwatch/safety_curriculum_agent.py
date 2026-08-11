from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from nightwatch.datasets import (
    assert_no_eval_leakage,
    canonical_prompt,
    find_near_duplicate_prompts,
    load_curriculum,
    load_eval_cases,
    maximum_prompt_similarity,
)

MODEL_ID = "gemini-3.6-flash"
GENERATION_PLAN = {
    "page_now": {
        "confirmed_data_corruption": 6,
        "confirmed_account_compromise": 6,
        "confirmed_total_outage": 6,
        "confirmed_severe_customer_harm": 6,
    },
    "investigate": {"ambiguous_multi_signal_risk": 4},
    "defer": {"verified_resolved_or_test": 4},
}
EXPECTED_COUNTS = {label: sum(groups.values()) for label, groups in GENERATION_PLAN.items()}
MAX_NEAR_DUPLICATE_JACCARD = 0.50


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_generated_rows(
    rows: Iterable[dict[str, object]],
    *,
    base_curriculum: list[dict[str, str]],
) -> list[dict[str, str]]:
    validated: list[dict[str, str]] = []
    seen = {canonical_prompt(row["prompt"]) for row in base_curriculum}
    counts: Counter[str] = Counter()
    group_counts: Counter[tuple[str, str]] = Counter()
    allowed_groups = {
        (label, group)
        for label, groups in GENERATION_PLAN.items()
        for group in groups
    }

    for index, row in enumerate(rows, start=1):
        prompt = row.get("prompt")
        label = row.get("label")
        group = row.get("generation_group")
        rationale = row.get("teacher_rationale")
        if not isinstance(prompt, str) or not 20 <= len(prompt.strip()) <= 1_000:
            raise ValueError(f"generated row {index}: prompt must contain 20 to 1,000 characters")
        if not isinstance(label, str) or not isinstance(group, str) or (label, group) not in allowed_groups:
            raise ValueError(f"generated row {index}: label and generation_group violate the fixed plan")
        if not isinstance(rationale, str) or not 20 <= len(rationale.strip()) <= 500:
            raise ValueError(
                f"generated row {index}: teacher_rationale must contain 20 to 500 characters"
            )
        fingerprint = canonical_prompt(prompt)
        if fingerprint in seen:
            raise ValueError(f"generated row {index}: duplicate canonical prompt")
        seen.add(fingerprint)
        counts[label] += 1
        group_counts[(label, group)] += 1
        validated.append(
            {
                "prompt": prompt.strip(),
                "label": label,
                "generation_group": group,
                "teacher_rationale": rationale.strip(),
                "teacher_model": MODEL_ID,
            }
        )

    if dict(counts) != EXPECTED_COUNTS:
        raise ValueError(f"generated label counts must be {EXPECTED_COUNTS}; received {dict(counts)}")
    expected_groups = {
        (label, group): count
        for label, groups in GENERATION_PLAN.items()
        for group, count in groups.items()
    }
    if dict(group_counts) != expected_groups:
        raise ValueError(
            f"generated group counts must be {expected_groups}; received {dict(group_counts)}"
        )
    return validated


async def _generate_rows() -> list[dict[str, object]]:
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise SystemExit("Agent dependencies are missing. Run: uv sync --extra agent") from exc

    required_count = sum(EXPECTED_COUNTS.values())

    class GeneratedExample(BaseModel):
        prompt: str = Field(min_length=20, max_length=1_000)
        label: str
        generation_group: str
        teacher_rationale: str = Field(min_length=20, max_length=500)

    class GeneratedBatch(BaseModel):
        examples: list[GeneratedExample] = Field(
            min_length=required_count,
            max_length=required_count,
        )

    agent = LlmAgent(
        name="v0_safety_hard_negative_teacher",
        model=MODEL_ID,
        description="Creates independently generated safety-boundary examples for a triage student.",
        instruction=(
            "Generate exactly 32 fictional operational-alert examples according to generation_plan. "
            "Use the exact label and generation_group names and exact counts. Every prompt must be "
            "independently classifiable from explicit evidence. page_now examples must state confirmed "
            "harm, compromise, corruption, or outage; investigate examples must contain ambiguous but "
            "credible risk without confirmed severe impact; defer examples must be explicitly test-only, "
            "planned, resolved, or transient with recovery verified. Provide a concise teacher_rationale "
            "that identifies the decisive evidence without referring to any dataset or answer key. Never "
            "generate a superficially healthy service whose downstream business outcome silently stops, "
            "stays empty, or fails to advance. Never request, infer, reproduce, or mention evaluation or "
            "development prompts. Vary systems, wording, scope, and evidence; do not use ALERT/INFO prefixes."
        ),
        output_schema=GeneratedBatch,
        output_key="v0_safety_hard_negative_batch",
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            events = await InMemoryRunner(agent=agent).run_debug(
                json.dumps(
                    {
                        "generation_plan": GENERATION_PLAN,
                        "generation_attempt": attempt,
                        "fixed_constraints": {
                            "examples": required_count,
                            "withheld_behavior": "healthy-looking silent downstream business stall",
                            "no_eval_or_dev_content": True,
                        },
                    },
                    sort_keys=True,
                ),
                quiet=True,
            )
            final_text = ""
            for event in events:
                if event.is_final_response() and event.content:
                    final_text = "".join(
                        part.text or ""
                        for part in event.content.parts
                        if not getattr(part, "thought", False)
                    )
            batch = GeneratedBatch.model_validate_json(final_text)
            return [item.model_dump() for item in batch.examples]
        except Exception as exc:
            last_error = exc
    raise SystemExit(
        "Gemini failed to return the fixed safety batch after three attempts: "
        f"{type(last_error).__name__}"
    )


async def generate(
    base_path: Path,
    dev_path: Path,
    frozen_path: Path,
    output_path: Path,
    evidence_path: Path,
) -> dict[str, object]:
    base = load_curriculum(base_path)
    generated = _validate_generated_rows(await _generate_rows(), base_curriculum=base)
    generated_for_checks = [{"prompt": row["prompt"], "label": row["label"]} for row in generated]
    dev_cases = load_eval_cases(dev_path)
    frozen_cases = load_eval_cases(frozen_path)
    assert_no_eval_leakage(generated_for_checks, dev_cases)
    assert_no_eval_leakage(generated_for_checks, frozen_cases)
    advisories = {
        "development": find_near_duplicate_prompts(
            generated_for_checks,
            dev_cases,
            threshold=MAX_NEAR_DUPLICATE_JACCARD,
        ),
        "frozen": find_near_duplicate_prompts(
            generated_for_checks,
            frozen_cases,
            threshold=MAX_NEAR_DUPLICATE_JACCARD,
        ),
    }
    if advisories["development"] or advisories["frozen"]:
        raise ValueError("generated safety curriculum is too similar to retained evaluation evidence")

    combined = [*base, *generated]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in combined) + "\n",
        encoding="utf-8",
    )
    evidence = {
        "teacher_model": MODEL_ID,
        "generation_plan": GENERATION_PLAN,
        "base_sha256": _sha256(base_path),
        "output_sha256": _sha256(output_path),
        "generated_examples": len(generated),
        "total_examples": len(combined),
        "maximum_similarity": {
            "development": maximum_prompt_similarity(generated_for_checks, dev_cases).to_dict(),
            "frozen": maximum_prompt_similarity(generated_for_checks, frozen_cases).to_dict(),
        },
        "generated_rows": generated,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {key: value for key, value in evidence.items() if key != "generated_rows"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the single predeclared v0 safety-hard-negative augmentation"
    )
    parser.add_argument("--base", type=Path, default=Path("artifacts/v0-curriculum.jsonl"))
    parser.add_argument("--dev", type=Path, default=Path("artifacts/v0-dev.jsonl"))
    parser.add_argument("--frozen", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/v0-safety-augmented-curriculum.jsonl"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("artifacts/v0-safety-augmentation-evidence.json"),
    )
    args = parser.parse_args()
    summary = asyncio.run(generate(args.base, args.dev, args.frozen, args.output, args.evidence))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
