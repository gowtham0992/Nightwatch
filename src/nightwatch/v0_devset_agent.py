from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from nightwatch.datasets import (
    canonical_prompt,
    find_near_duplicate_prompts,
    load_curriculum,
    load_eval_cases,
    maximum_prompt_similarity,
)

MODEL_ID = "gemini-3.6-flash"
DEV_SPECS: dict[str, dict[str, object]] = {
    "target": {
        "size": 40,
        "labels": {"page_now": 29, "investigate": 11},
        "critical": 0,
        "brief": (
            "Silent operational failures where surface health, success codes, heartbeats, or job status "
            "appear healthy while an expected downstream business outcome stops, stays empty, or fails "
            "to advance. Include both urgent and ambiguous cases."
        ),
    },
    "regression": {
        "size": 80,
        "labels": {"page_now": 30, "investigate": 22, "defer": 28},
        "critical": 0,
        "brief": (
            "Ordinary operational triage spanning explicit outages, serious customer impact, ambiguous "
            "degradation, capacity risks, localized failures, benign development activity, planned changes, "
            "and transient recovered events. Exclude silent downstream business-outcome stalls."
        ),
    },
    "safety": {
        "size": 30,
        "labels": {"page_now": 27, "investigate": 3},
        "critical": 20,
        "brief": (
            "High-consequence security, payment, medical, privacy, corruption, and physical-safety events. "
            "Exactly twenty page_now cases must be marked safety_critical; other cases are serious but not "
            "in the critical subset."
        ),
    },
}


async def _generate_suite(suite: str, spec: dict[str, object]) -> list[dict[str, object]]:
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise SystemExit("Agent dependencies are missing. Run: uv sync --extra agent") from exc

    required_count = int(spec["size"])

    class DevExample(BaseModel):
        prompt: str = Field(min_length=10, max_length=1_000)
        label: str = Field(pattern="^(page_now|investigate|defer)$")
        safety_critical: bool

    class DevBatch(BaseModel):
        examples: list[DevExample] = Field(
            min_length=required_count,
            max_length=required_count,
        )

    agent = LlmAgent(
        name=f"v0_{suite}_devset_architect",
        model=MODEL_ID,
        description="Creates held-out, naturally worded operational triage development cases.",
        instruction=(
            f"Generate exactly {required_count} held-out {suite} cases matching the supplied specification. "
            f"The exact label quotas are {spec['labels']}; the exact safety_critical count is "
            f"{spec['critical']}. Use concise natural language, not templated ALERT/INFO prefixes. Include "
            "hard boundaries and lexical variety. Never reproduce, infer, or request hidden frozen prompts "
            "or training examples. Return only the structured batch."
        ),
        output_schema=DevBatch,
        output_key=f"v0_{suite}_devset",
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            events = await InMemoryRunner(agent=agent).run_debug(
                json.dumps({"suite": suite, **spec, "attempt": attempt}, sort_keys=True),
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
            batch = DevBatch.model_validate_json(final_text)
            rows = [item.model_dump() for item in batch.examples]
            expected_labels = Counter(
                {label: int(count) for label, count in dict(spec["labels"]).items()}
            )
            if Counter(row["label"] for row in rows) != expected_labels:
                raise ValueError("label quotas do not match the predeclared specification")
            if sum(bool(row["safety_critical"]) for row in rows) != int(spec["critical"]):
                raise ValueError("safety_critical quota does not match the predeclared specification")
            if suite != "safety" and any(bool(row["safety_critical"]) for row in rows):
                raise ValueError("only safety-suite cases may be safety critical")
            return rows
        except Exception as exc:
            last_error = exc
    detail = str(last_error).replace("\n", " ")[:500]
    raise SystemExit(
        f"Gemini failed to produce the {suite} development batch: "
        f"{type(last_error).__name__}: {detail}"
    )


async def generate(
    output_path: Path,
    frozen_path: Path,
    curriculum_path: Path,
) -> dict[str, object]:
    generated: list[dict[str, object]] = []
    for suite, spec in DEV_SPECS.items():
        if int(spec["size"]) > 40:
            label_counts = {label: int(count) for label, count in dict(spec["labels"]).items()}
            first_labels = {label: count // 2 for label, count in label_counts.items()}
            second_labels = {
                label: count - first_labels[label] for label, count in label_counts.items()
            }
            first_size = sum(first_labels.values())
            parts = [
                {**spec, "size": first_size, "labels": first_labels},
                {
                    **spec,
                    "size": int(spec["size"]) - first_size,
                    "labels": second_labels,
                },
            ]
            rows = []
            for part_index, part_spec in enumerate(parts, start=1):
                rows.extend(await _generate_suite(f"{suite}_part_{part_index}", part_spec))
        else:
            rows = await _generate_suite(suite, spec)
        for index, row in enumerate(rows, start=1):
            generated.append(
                {
                    "id": f"dev-{suite}-{index:03d}",
                    "suite": suite,
                    "prompt": row["prompt"],
                    "expected_label": row["label"],
                    "safety_critical": row["safety_critical"],
                }
            )

    prompts = [canonical_prompt(str(row["prompt"])) for row in generated]
    if len(prompts) != len(set(prompts)):
        raise SystemExit("Development set contains duplicate canonical prompts")
    forbidden_prompts = {
        canonical_prompt(case.prompt) for case in load_eval_cases(frozen_path)
    } | {
        canonical_prompt(row["prompt"]) for row in load_curriculum(curriculum_path)
    }
    if leaked := sorted(set(prompts) & forbidden_prompts):
        raise SystemExit(f"Development set overlaps protected evidence: {len(leaked)} prompts")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in generated) + "\n",
        encoding="utf-8",
    )
    dev_cases = load_eval_cases(output_path)
    frozen_cases = load_eval_cases(frozen_path)
    advisories = find_near_duplicate_prompts(
        [{"prompt": case.prompt, "label": case.expected_label} for case in dev_cases],
        frozen_cases,
        threshold=0.5,
    )
    maximum = maximum_prompt_similarity(
        [{"prompt": case.prompt, "label": case.expected_label} for case in dev_cases],
        frozen_cases,
    )
    return {
        "examples": len(generated),
        "near_duplicate_advisories": [item.to_dict() for item in advisories],
        "maximum_token_jaccard": maximum.to_dict() if maximum else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the independent Nightwatch v0 development set")
    parser.add_argument("--output", type=Path, default=Path("artifacts/v0-dev.jsonl"))
    parser.add_argument("--frozen", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument(
        "--curriculum",
        type=Path,
        default=Path("artifacts/v0-curriculum.jsonl"),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(generate(args.output, args.frozen, args.curriculum)),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
