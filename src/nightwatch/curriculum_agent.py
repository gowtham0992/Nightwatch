from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

MODEL_ID = "gemini-3.6-flash"


def _load_diagnosis(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"target_behavior", "failure_patterns", "constraints"}
    if not isinstance(raw, dict) or not required <= set(raw):
        raise SystemExit(f"Diagnosis must be an object containing {sorted(required)}")
    encoded = json.dumps(raw)
    if len(encoded) > 20_000:
        raise SystemExit("Diagnosis exceeds the 20,000 character boundary")
    return raw


async def generate(diagnosis_path: Path, output_path: Path, examples: int) -> None:
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise SystemExit("Agent dependencies are missing. Run: uv sync --extra agent") from exc

    class CurriculumExample(BaseModel):
        prompt: str = Field(min_length=10, max_length=1_000)
        label: str = Field(pattern="^(page_now|investigate|defer)$")
        rationale: str = Field(min_length=5, max_length=500)

    class CurriculumPlan(BaseModel):
        examples: list[CurriculumExample]

    agent = LlmAgent(
        name="curriculum_architect",
        model=MODEL_ID,
        description="Builds targeted small-model curricula from aggregate failure diagnoses.",
        instruction=(
            f"Generate exactly {examples} diverse alert-triage examples from the supplied aggregate diagnosis. "
            "Never reproduce or guess hidden evaluation prompts. Labels are page_now, investigate, or defer. "
            "Cover both the target failure and nearby negative examples so the student does not overcall."
        ),
        output_schema=CurriculumPlan,
        output_key="curriculum_plan",
    )
    events = await InMemoryRunner(agent=agent).run_debug(
        json.dumps(_load_diagnosis(diagnosis_path), sort_keys=True),
        quiet=True,
    )
    final_text = ""
    for event in events:
        if event.is_final_response() and event.content:
            final_text = "".join(part.text or "" for part in event.content.parts if not getattr(part, "thought", False))
    plan = CurriculumPlan.model_validate_json(final_text)
    if len(plan.examples) != examples:
        raise SystemExit(f"Agent returned {len(plan.examples)} examples; expected exactly {examples}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(
            json.dumps({"prompt": item.prompt, "label": item.label}, sort_keys=True)
            for item in plan.examples
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a bounded Nightwatch curriculum with Google ADK")
    parser.add_argument("--diagnosis", type=Path, default=Path("data/diagnosis/silent_failure.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/generated_curriculum.jsonl"))
    parser.add_argument("--examples", type=int, default=32)
    args = parser.parse_args()
    if not 8 <= args.examples <= 200:
        raise SystemExit("--examples must be between 8 and 200")
    asyncio.run(generate(args.diagnosis, args.output, args.examples))


if __name__ == "__main__":
    main()

