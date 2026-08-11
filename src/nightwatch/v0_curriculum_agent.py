from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from nightwatch.datasets import (
    assert_no_eval_leakage,
    find_near_duplicate_prompts,
    load_eval_cases,
    maximum_prompt_similarity,
)
from nightwatch.v0 import V0_CATEGORIES, balanced_category_counts, validate_v0_curriculum

MODEL_ID = "gemini-3.6-flash"


def _load_brief(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"student_role", "allowed_taxonomy", "withheld_behavior", "constraints"}
    if not isinstance(raw, dict) or not required <= set(raw):
        raise SystemExit(f"Brief must be an object containing {sorted(required)}")
    taxonomy = raw["allowed_taxonomy"]
    if not isinstance(taxonomy, dict) or {
        str(label): frozenset(categories) if isinstance(categories, list) else frozenset()
        for label, categories in taxonomy.items()
    } != V0_CATEGORIES:
        raise SystemExit("Brief taxonomy does not match the code-enforced v0 taxonomy")
    if len(json.dumps(raw)) > 20_000:
        raise SystemExit("Brief exceeds the 20,000 character boundary")
    return raw


async def _generate_category_batch(
    brief: dict[str, object],
    *,
    label: str,
    category: str,
    examples: int,
) -> list[dict[str, object]]:
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise SystemExit("Agent dependencies are missing. Run: uv sync --extra agent") from exc

    required_count = examples

    class GeneratedExample(BaseModel):
        prompt: str = Field(min_length=10, max_length=1_000)

    class GeneratedBatch(BaseModel):
        examples: list[GeneratedExample] = Field(
            min_length=required_count,
            max_length=required_count,
        )

    agent = LlmAgent(
        name=f"v0_{label}_{category}_curriculum_architect",
        model=MODEL_ID,
        description="Builds non-target operational triage curricula for a deployable v0 student.",
        instruction=(
            f"Generate exactly {examples} diverse, independently classifiable operational alerts whose "
            f"correct label is {label} and whose scenario category is exactly {category}. "
            "Vary the surface form: monitoring alerts, plain incident descriptions, maintenance notices, "
            "resolved events, and concise log summaries where appropriate. Do not mechanically prefix every "
            "example with ALERT or repeat one environment, service, or explanation template. "
            "Obey the withheld_behavior literally: never generate a superficially healthy system whose "
            "expected downstream business state silently stops, stays empty, or fails to advance. "
            "Never reproduce or guess hidden evaluation prompts. Return only the structured batch."
        ),
        output_schema=GeneratedBatch,
        output_key=f"v0_{label}_{category}_batch",
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            events = await InMemoryRunner(agent=agent).run_debug(
                json.dumps(
                    {
                        **brief,
                        "generation_attempt": attempt,
                        "exact_required_count": examples,
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
            return [
                {"prompt": item.prompt, "label": label, "category": category}
                for item in batch.examples
            ]
        except Exception as exc:
            last_error = exc
    raise SystemExit(
        f"Agent failed to return exactly {examples} valid {label}/{category} examples after 3 attempts: "
        f"{type(last_error).__name__}"
    )


async def generate(
    brief_path: Path,
    output_path: Path,
    eval_path: Path,
    *,
    examples_per_label: int,
) -> dict[str, object]:
    brief = _load_brief(brief_path)
    rows: list[dict[str, object]] = []
    for label in ("page_now", "investigate", "defer"):
        for category, examples in balanced_category_counts(label, examples_per_label).items():
            rows.extend(
                await _generate_category_batch(
                    brief,
                    label=label,
                    category=category,
                    examples=examples,
                )
            )
    validated = validate_v0_curriculum(rows, expected_per_label=examples_per_label)
    eval_cases = load_eval_cases(eval_path)
    assert_no_eval_leakage(validated, eval_cases)
    advisories = find_near_duplicate_prompts(validated, eval_cases, threshold=0.5)
    maximum = maximum_prompt_similarity(validated, eval_cases)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in validated) + "\n",
        encoding="utf-8",
    )
    return {
        "examples": len(validated),
        "examples_per_label": examples_per_label,
        "near_duplicate_advisories": [item.to_dict() for item in advisories],
        "maximum_token_jaccard": maximum.to_dict() if maximum else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the target-withheld v0 curriculum with Gemini and Google ADK"
    )
    parser.add_argument("--brief", type=Path, default=Path("data/diagnosis/base_triage.json"))
    parser.add_argument("--eval", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/v0-curriculum.jsonl"))
    parser.add_argument("--examples-per-label", type=int, default=80)
    args = parser.parse_args()
    if not 20 <= args.examples_per_label <= 100:
        raise SystemExit("--examples-per-label must be between 20 and 100")
    summary = asyncio.run(
        generate(
            args.brief,
            args.output,
            args.eval,
            examples_per_label=args.examples_per_label,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
