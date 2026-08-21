from __future__ import annotations

import asyncio
import json
from typing import Any

from nightwatch.datasets import canonical_prompt
from nightwatch.journal import JournalError
from nightwatch.operator_contracts import MissionContract

GEMINI_AGENT_MODEL = "gemini-3.6-flash"
SPECIALISTS = ("target_repair", "safety_boundary", "regression_guard")
SPECIALIST_BRIEFS = {
    "target_repair": "Repair the failure patterns observed in the target suite.",
    "safety_boundary": "Strengthen critical safety decisions without weakening the approved boundary.",
    "regression_guard": "Preserve protected routine behavior while the target boundary changes.",
}


async def _structured_agent(
    *, name: str, description: str, instruction: str, schema: type, request: dict[str, Any]
) -> dict[str, Any]:
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
    except ImportError as exc:
        raise RuntimeError("Google ADK dependencies are not installed") from exc
    agent = LlmAgent(
        name=name,
        model=GEMINI_AGENT_MODEL,
        description=description,
        instruction=instruction,
        output_schema=schema,
        output_key=f"{name}_output",
    )
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            events = await InMemoryRunner(agent=agent).run_debug(
                json.dumps({**request, "attempt": attempt}, sort_keys=True), quiet=True
            )
            final_text = ""
            for event in events:
                if event.is_final_response() and event.content:
                    final_text = "".join(
                        part.text or ""
                        for part in event.content.parts
                        if not getattr(part, "thought", False)
                    )
            return schema.model_validate_json(final_text).model_dump()
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"{name} failed its bounded output contract: {type(last_error).__name__}")


async def diagnose_failures(
    failure_packet: dict[str, Any], contract: MissionContract
) -> dict[str, Any]:
    try:
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Google ADK dependencies are not installed") from exc

    class Diagnosis(BaseModel):
        headline: str = Field(min_length=12, max_length=160)
        failure_pattern: str = Field(min_length=30, max_length=700)
        evidence_case_ids: list[str] = Field(min_length=1, max_length=8)
        repair_objective: str = Field(min_length=20, max_length=500)
        protected_behaviors: list[str] = Field(min_length=2, max_length=6)

    result = await _structured_agent(
        name="nightwatch_generic_diagnostician",
        description="Diagnoses bounded classifier failures from immutable evidence.",
        instruction=(
            "Use only supplied misclassified rows. Cite observed case IDs. Explain the smallest "
            "repairable pattern without hidden reasoning. Never change labels, thresholds, model, "
            "dataset, compute limits, or deployment state. Preserve regression and safety behavior."
        ),
        schema=Diagnosis,
        request={"failure_packet": failure_packet, "labels": list(contract.labels)},
    )
    allowed = {str(row["case_id"]) for row in failure_packet.get("errors", [])}
    cited = result.get("evidence_case_ids")
    if not isinstance(cited, list) or not set(cited) <= allowed:
        raise JournalError("diagnostician cited evidence outside the frozen baseline scan")
    return result


async def author_parallel_curriculum(
    diagnosis: dict[str, Any], failure_packet: dict[str, Any], contract: MissionContract
) -> dict[str, Any]:
    try:
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Google ADK dependencies are not installed") from exc

    class Example(BaseModel):
        text: str = Field(min_length=3, max_length=1000)
        label: str = Field(min_length=1, max_length=64)

    class AuthoredBatch(BaseModel):
        rationale: str = Field(min_length=20, max_length=400)
        examples: list[Example] = Field(min_length=8, max_length=16)

    async def author(specialist: str) -> dict[str, Any]:
        assignment = SPECIALIST_BRIEFS[specialist]
        batch = await _structured_agent(
            name=f"nightwatch_{specialist}",
            description=f"Authors bounded classifier curriculum for {specialist}.",
            instruction=(
                f"You are the {specialist} specialist. Your assignment is: {assignment} "
                "Create 8 to 16 original training examples "
                "using only approved labels and include every approved label at least once. Do not "
                "copy or closely paraphrase evaluation text. "
                "Do not introduce new labels, code, URLs, actions, or policy changes. "
                "Return concise observable examples."
            ),
            schema=AuthoredBatch,
            request={
                "specialist": specialist,
                "assignment": assignment,
                "diagnosis": diagnosis,
                "observed_errors": failure_packet.get("errors", []),
                "labels": list(contract.labels),
                "classification_instruction": contract.instruction,
            },
        )
        # The orchestrator owns agent identity. Model-authored content must never
        # be trusted to identify which bounded invocation produced it.
        return {**batch, "specialist": specialist, "assignment": assignment}

    batches = await asyncio.gather(*(author(specialist) for specialist in SPECIALISTS))
    evaluation_prompts = {
        canonical_prompt(str(row["text"]))
        for row in failure_packet.get("all_cases", [])
        if isinstance(row, dict) and isinstance(row.get("text"), str)
    }
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for specialist, batch in zip(SPECIALISTS, batches, strict=True):
        if batch.get("specialist") != specialist:
            raise JournalError("curriculum invocation identity was not bound by the orchestrator")
        examples = batch.get("examples")
        if not isinstance(examples, list) or not 8 <= len(examples) <= 16:
            raise JournalError("curriculum specialist returned an invalid batch size")
        if {example.get("label") for example in examples} != set(contract.labels):
            raise JournalError("curriculum specialist did not cover every approved label")
        for example in examples:
            text = str(example.get("text", "")).strip()
            label = example.get("label")
            fingerprint = canonical_prompt(text)
            if label not in contract.labels or fingerprint in seen or fingerprint in evaluation_prompts:
                raise JournalError("authored curriculum violates labels, uniqueness, or leakage policy")
            seen.add(fingerprint)
            rows.append({"text": text, "label": str(label), "specialist": specialist})
    return {"specialists": list(SPECIALISTS), "batches": batches, "rows": rows}
