from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from nightwatch.contracts import Prediction
from nightwatch.scam_safety import (
    ALLOWED_SCAM_LABELS,
    evaluate_scam_safety,
    load_scam_eval_cases,
    load_scam_mission,
)


MODEL_ID = "gemini-3.6-flash"
ALLOWED_REPAIR_FAMILIES = frozenset(
    {
        "plausible_notice_harmful_ask",
        "official_route_safe_contrast",
        "upfront_fee_job_fraud",
        "credential_request_delivery_fraud",
        "unsolicited_link_caution_boundary",
        "legitimate_notice_verify_boundary",
        "ordinary_message_routine_boundary",
    }
)
_PLAN_KEYS = {
    "headline",
    "failure_pattern",
    "evidence_case_ids",
    "repair_objective",
    "repair_families",
    "examples_per_family",
    "protected_behaviors",
    "success_signal",
}
_CASE_ID = re.compile(r"^[a-z][a-z0-9_-]{2,127}$")
_SAFETY_BLOCK_REPAIR_FAMILIES = frozenset(
    {
        "plausible_notice_harmful_ask",
        "upfront_fee_job_fraud",
        "credential_request_delivery_fraud",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _required_text(value: object, field: str, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    text = value.strip()
    if not minimum <= len(text) <= maximum:
        raise ValueError(f"{field} must contain {minimum} to {maximum} characters")
    return text


def _prediction_rows(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read predictions: {path}") from exc
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid prediction JSON") from exc
        if not isinstance(row, dict) or set(row) != {"confidence", "id", "label"}:
            raise ValueError(f"{path}:{line_number}: prediction keys do not match contract")
        case_id = row.get("id")
        label = row.get("label")
        confidence = row.get("confidence")
        if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id):
            raise ValueError(f"{path}:{line_number}: invalid prediction id")
        if case_id in seen:
            raise ValueError(f"{path}:{line_number}: duplicate prediction id")
        if label not in ALLOWED_SCAM_LABELS:
            raise ValueError(f"{path}:{line_number}: invalid prediction label")
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError(f"{path}:{line_number}: invalid prediction confidence")
        seen.add(case_id)
        rows.append({"id": case_id, "label": label, "confidence": float(confidence)})
    if not rows:
        raise ValueError(f"predictions are empty: {path}")
    return rows


def build_scam_failure_packet(
    mission_path: Path,
    development_path: Path,
    predictions_path: Path,
    report_path: Path,
) -> dict[str, object]:
    mission = load_scam_mission(mission_path)
    cases = load_scam_eval_cases(development_path)
    prediction_rows = _prediction_rows(predictions_path)
    try:
        retained = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read retained evaluation report: {report_path}") from exc
    if not isinstance(retained, dict):
        raise ValueError("retained evaluation report must be an object")
    artifact_name = retained.get("artifact_name")
    retained_evaluation = retained.get("development_evaluation")
    if not isinstance(artifact_name, str) or not isinstance(retained_evaluation, dict):
        raise ValueError("retained evaluation report is missing baseline evidence")
    if retained.get("mission_id") != mission.mission_id:
        raise ValueError("retained evaluation report does not match the mission")
    expected_hashes = {
        "mission_sha256": _sha256(mission_path),
        "development_sha256": _sha256(development_path),
    }
    if any(retained.get(key) != value for key, value in expected_hashes.items()):
        raise ValueError("retained evaluation report does not match the source evidence")

    predictions = [
        Prediction(case_id=str(row["id"]), label=str(row["label"]))
        for row in prediction_rows
    ]
    recomputed = evaluate_scam_safety(artifact_name, cases, predictions).to_dict()
    if recomputed != retained_evaluation:
        raise ValueError("prediction evidence does not match the retained evaluation report")
    by_id = {str(row["id"]): row for row in prediction_rows}
    errors = []
    for case in cases:
        prediction = by_id[case.case_id]
        if prediction["label"] == case.expected_label:
            continue
        errors.append(
            {
                "case_id": case.case_id,
                "suite": case.suite.value,
                "message": case.message,
                "threat_family": case.threat_family,
                "expected_label": case.expected_label,
                "predicted_label": prediction["label"],
                "confidence": prediction["confidence"],
                "safety_critical": case.safety_critical,
            }
        )
    return {
        "mission_id": mission.mission_id,
        "artifact_name": artifact_name,
        "error_count": len(errors),
        "scores": retained_evaluation["scores"],
        "critical_misses": retained_evaluation["critical_misses"],
        "errors": errors,
        "source_hashes": {
            **expected_hashes,
            "predictions_sha256": _sha256(predictions_path),
            "report_sha256": _sha256(report_path),
        },
    }


def validate_scam_repair_plan(
    raw: object,
    *,
    allowed_evidence_ids: set[str],
    required_safety_ids: set[str] | None = None,
) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != _PLAN_KEYS:
        missing = sorted(_PLAN_KEYS - set(raw) if isinstance(raw, dict) else _PLAN_KEYS)
        unknown = sorted(set(raw) - _PLAN_KEYS if isinstance(raw, dict) else set())
        raise ValueError(f"repair plan keys do not match contract; missing={missing}, unknown={unknown}")
    evidence = raw["evidence_case_ids"]
    if (
        not isinstance(evidence, list)
        or not 2 <= len(evidence) <= 6
        or any(not isinstance(value, str) for value in evidence)
        or len(set(evidence)) != len(evidence)
    ):
        raise ValueError("evidence_case_ids must contain 2 to 6 unique ids")
    if not set(evidence) <= allowed_evidence_ids:
        raise ValueError("repair plan cites unobserved evidence")
    families = raw["repair_families"]
    if (
        not isinstance(families, list)
        or not 2 <= len(families) <= 4
        or any(not isinstance(value, str) for value in families)
        or len(set(families)) != len(families)
    ):
        raise ValueError("repair_families must contain 2 to 4 unique values")
    if not set(families) <= ALLOWED_REPAIR_FAMILIES:
        raise ValueError("repair plan contains an unsupported repair family")
    required_safety_ids = required_safety_ids or set()
    if required_safety_ids and (
        not set(evidence) & required_safety_ids
        or not set(families) & _SAFETY_BLOCK_REPAIR_FAMILIES
    ):
        raise ValueError(
            "repair plan does not address the observed safety block deficit"
        )
    examples = raw["examples_per_family"]
    if isinstance(examples, bool) or examples not in {12, 16, 20, 24}:
        raise ValueError("examples_per_family must be 12, 16, 20, or 24")
    protected = raw["protected_behaviors"]
    if (
        not isinstance(protected, list)
        or not 2 <= len(protected) <= 5
        or any(not isinstance(value, str) for value in protected)
    ):
        raise ValueError("protected_behaviors must contain 2 to 5 statements")
    return {
        "headline": _required_text(raw["headline"], "headline", minimum=20, maximum=160),
        "failure_pattern": _required_text(
            raw["failure_pattern"], "failure_pattern", minimum=40, maximum=700
        ),
        "evidence_case_ids": list(evidence),
        "repair_objective": _required_text(
            raw["repair_objective"], "repair_objective", minimum=30, maximum=500
        ),
        "repair_families": list(families),
        "examples_per_family": int(examples),
        "protected_behaviors": [
            _required_text(value, "protected_behavior", minimum=20, maximum=300)
            for value in protected
        ],
        "success_signal": _required_text(
            raw["success_signal"], "success_signal", minimum=30, maximum=500
        ),
    }


async def author_scam_repair_plan(packet: dict[str, object]) -> dict[str, object]:
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise SystemExit("Agent dependencies are missing. Run: uv sync --extra agent") from exc

    class RepairPlan(BaseModel):
        headline: str = Field(min_length=20, max_length=160)
        failure_pattern: str = Field(min_length=40, max_length=700)
        evidence_case_ids: list[str] = Field(min_length=2, max_length=6)
        repair_objective: str = Field(min_length=30, max_length=500)
        repair_families: list[str] = Field(min_length=2, max_length=4)
        examples_per_family: int
        protected_behaviors: list[str] = Field(min_length=2, max_length=5)
        success_signal: str = Field(min_length=30, max_length=500)

    agent = LlmAgent(
        name="nightwatch_scam_diagnostician",
        model=MODEL_ID,
        description="Diagnoses retained small-model failures and designs a bounded repair curriculum.",
        instruction=(
            "Analyze only the supplied retained development failures. Identify the smallest coherent "
            "failure pattern supported by at least two cited case IDs, prioritizing harmful false negatives "
            "and their safe contrast boundary. Do not invent evidence, change labels, change the release "
            "gate, request sealed data, or prescribe a general retraining run. Choose 2 to 4 repair families "
            "only from allowed_repair_families and choose examples_per_family from 12, 16, 20, or 24. "
            "Protected behaviors must state what the repair must not damage. Write observable evidence and "
            "a concise operational objective; do not provide hidden chain-of-thought. If an expected-block "
            "safety case was softened, cite that case and select a harmful-ask repair family even when other "
            "errors form a larger cluster."
        ),
        output_schema=RepairPlan,
        output_key="scam_repair_plan",
    )
    request = {
        "failure_packet": packet,
        "allowed_repair_families": sorted(ALLOWED_REPAIR_FAMILIES),
    }
    last_error: Exception | None = None
    allowed_ids = {str(row["case_id"]) for row in packet["errors"]}
    required_safety_ids = {
        str(row["case_id"])
        for row in packet["errors"]
        if row["suite"] == "safety"
        and row["expected_label"] == "block"
        and row["predicted_label"] != "block"
    }
    for attempt in range(1, 3):
        try:
            events = await InMemoryRunner(agent=agent).run_debug(
                json.dumps({**request, "attempt": attempt}, sort_keys=True),
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
            parsed = RepairPlan.model_validate_json(final_text).model_dump()
            return validate_scam_repair_plan(
                parsed,
                allowed_evidence_ids=allowed_ids,
                required_safety_ids=required_safety_ids,
            )
        except Exception as exc:
            last_error = exc
    raise RuntimeError(
        "diagnosis agent failed the bounded repair-plan contract after two attempts: "
        f"{type(last_error).__name__}: {str(last_error)[:500]}"
    )


async def run(args: argparse.Namespace) -> None:
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite retained repair plan: {output}")
    packet = build_scam_failure_packet(
        Path(args.mission),
        Path(args.development),
        Path(args.predictions),
        Path(args.report),
    )
    plan = await author_scam_repair_plan(packet)
    evidence = {
        "schema_version": 1,
        "author_model": MODEL_ID,
        "mission_id": packet["mission_id"],
        "artifact_name": packet["artifact_name"],
        "source_hashes": packet["source_hashes"],
        "plan": plan,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "plan": plan}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose retained Nightwatch scam-safety failures")
    parser.add_argument("--mission", default="data/scam_safety/mission.json")
    parser.add_argument("--development", default="data/scam_safety/development-v0.jsonl")
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
