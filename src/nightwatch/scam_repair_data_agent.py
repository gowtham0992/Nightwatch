from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from nightwatch.datasets import canonical_prompt
from nightwatch.scam_data_agent import (
    MAX_TRAIN_EVAL_JACCARD,
    MODEL_ID,
    _author_batch,
    _jsonl,
    _validated_authored_rows,
    maximum_train_eval_jaccard,
)
from nightwatch.scam_repair_agent import validate_scam_repair_plan
from nightwatch.scam_safety import (
    BLOCK,
    CAUTION,
    ROUTINE,
    VERIFY,
    assert_no_scam_eval_leakage,
    load_scam_curriculum,
    load_scam_eval_cases,
)


REPAIR_FAMILY_LABELS = {
    "plausible_notice_harmful_ask": BLOCK,
    "official_route_safe_contrast": VERIFY,
    "upfront_fee_job_fraud": BLOCK,
    "credential_request_delivery_fraud": BLOCK,
    "unsolicited_link_caution_boundary": CAUTION,
    "legitimate_notice_verify_boundary": VERIFY,
    "ordinary_message_routine_boundary": ROUTINE,
}
TARGET_EXAMPLES_PER_FAMILY = 12


def validate_family_rows(
    rows: list[dict[str, Any]],
    *,
    family: str,
    expected_count: int,
) -> list[dict[str, object]]:
    if family not in REPAIR_FAMILY_LABELS:
        raise ValueError(f"unsupported repair family: {family}")
    if len(rows) != expected_count:
        raise ValueError(f"expected {expected_count} rows; received {len(rows)}")
    label = REPAIR_FAMILY_LABELS[family]
    if any(row.get("label") != label for row in rows):
        raise ValueError(f"rows violate the fixed repair label for {family}")
    return _validated_authored_rows(
        rows,
        expected_count=expected_count,
        expected_labels={label: expected_count},
        allowed_families={family},
        expected_critical=0,
    )


def _load_plan(path: Path) -> tuple[dict[str, object], dict[str, object]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read retained repair plan: {path}") from exc
    expected = {
        "artifact_name",
        "author_model",
        "mission_id",
        "plan",
        "schema_version",
        "source_hashes",
    }
    if not isinstance(raw, dict) or set(raw) != expected or raw["schema_version"] != 1:
        raise ValueError("retained repair plan wrapper does not match contract")
    source_hashes = raw["source_hashes"]
    if not isinstance(source_hashes, dict):
        raise ValueError("retained repair plan source_hashes must be an object")
    evidence_ids = set(raw["plan"].get("evidence_case_ids", [])) if isinstance(raw["plan"], dict) else set()
    plan = validate_scam_repair_plan(raw["plan"], allowed_evidence_ids=evidence_ids)
    return raw, plan


async def _author_family(family: str, count: int, purpose: str) -> list[dict[str, object]]:
    label = REPAIR_FAMILY_LABELS[family]
    rows = await _author_batch(
        agent_name=f"repair_{purpose}_{family}",
        expected_count=count,
        expected_labels={label: count},
        allowed_families={family},
        expected_critical=0,
        purpose=(
            f"{purpose} for the diagnosed repair family {family}; create independent original "
            "messages and emphasize the observable requested action rather than sender framing"
        ),
    )
    return validate_family_rows(rows, family=family, expected_count=count)


def _read_original_non_target_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("suite") != "target":
            rows.append(row)
    if Counter(str(row.get("suite")) for row in rows) != Counter(
        {"regression": 32, "safety": 24}
    ):
        raise ValueError("original development evidence has unexpected protected-suite counts")
    return rows


async def author_repair_bundle(
    plan_path: Path,
    original_curriculum_path: Path,
    original_development_path: Path,
    target_path: Path,
    development_path: Path,
    repair_curriculum_path: Path,
    combined_curriculum_path: Path,
    evidence_path: Path,
) -> dict[str, object]:
    destinations = (
        target_path,
        development_path,
        repair_curriculum_path,
        combined_curriculum_path,
        evidence_path,
    )
    if any(path.exists() for path in destinations):
        raise FileExistsError("refusing to overwrite retained repair evidence")
    plan_wrapper, plan = _load_plan(plan_path)
    families = list(plan["repair_families"])
    if any(family not in REPAIR_FAMILY_LABELS for family in families):
        raise ValueError("repair plan contains a family without a fixed label policy")

    # Freeze the target evidence before the candidate curriculum exists.
    target_batches = await asyncio.gather(
        *(
            _author_family(family, TARGET_EXAMPLES_PER_FAMILY, "focused_target")
            for family in families
        )
    )
    target_rows: list[dict[str, object]] = []
    for family, rows in zip(families, target_batches, strict=True):
        for index, row in enumerate(rows, start=1):
            target_rows.append(
                {
                    "id": f"repair-target-{family}-{index:03d}",
                    "suite": "target",
                    "message": row["message"],
                    "expected_label": row["label"],
                    "threat_family": family,
                    "safety_critical": False,
                }
            )
    target_bytes = _jsonl(target_rows).encode()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(target_bytes)
    protected_rows = _read_original_non_target_rows(original_development_path)
    development_bytes = _jsonl(target_rows + protected_rows).encode()
    development_path.write_bytes(development_bytes)
    development = load_scam_eval_cases(development_path)

    original_curriculum = load_scam_curriculum(original_curriculum_path)
    repair_rows: list[dict[str, object]] = []
    similarity: dict[str, object] = {}
    for attempt in range(1, 4):
        batches = await asyncio.gather(
            *(
                _author_family(
                    family,
                    int(plan["examples_per_family"]),
                    f"curriculum_pass_{attempt}",
                )
                for family in families
            )
        )
        candidate = [row for batch in batches for row in batch]
        combined_for_similarity = [*original_curriculum, *candidate]
        similarity = maximum_train_eval_jaccard(
            combined_for_similarity,
            [
                {
                    "message": case.message,
                    "suite": case.suite.value,
                    "expected_label": case.expected_label,
                }
                for case in development
            ],
        )
        messages = [canonical_prompt(str(row["message"])) for row in candidate]
        if len(messages) == len(set(messages)) and float(similarity["score"]) < MAX_TRAIN_EVAL_JACCARD:
            repair_rows = candidate
            break
    if not repair_rows:
        raise ValueError("repair curriculum failed duplicate or similarity checks after three passes")

    repair_output = [
        {key: row[key] for key in ("message", "label", "threat_family", "rationale")}
        for row in repair_rows
    ]
    combined_output = [*original_curriculum, *repair_output]
    repair_bytes = _jsonl(repair_output).encode()
    combined_bytes = _jsonl(combined_output).encode()
    repair_curriculum_path.write_bytes(repair_bytes)
    combined_curriculum_path.write_bytes(combined_bytes)
    combined = load_scam_curriculum(combined_curriculum_path)
    assert_no_scam_eval_leakage(combined, development)

    evidence = {
        "schema_version": 1,
        "author_model": MODEL_ID,
        "baseline_artifact": plan_wrapper["artifact_name"],
        "repair_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "repair_families": families,
        "target_rows": len(target_rows),
        "repair_rows": len(repair_output),
        "combined_curriculum_rows": len(combined),
        "development_suite_counts": dict(Counter(case.suite.value for case in development)),
        "target_sha256": hashlib.sha256(target_bytes).hexdigest(),
        "development_sha256": hashlib.sha256(development_bytes).hexdigest(),
        "repair_curriculum_sha256": hashlib.sha256(repair_bytes).hexdigest(),
        "combined_curriculum_sha256": hashlib.sha256(combined_bytes).hexdigest(),
        "maximum_train_eval_token_jaccard": similarity,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="Author frozen Nightwatch repair evidence with Gemini ADK")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--original-curriculum", type=Path, default=Path("data/scam_safety/curriculum-v0.jsonl"))
    parser.add_argument("--original-development", type=Path, default=Path("data/scam_safety/development-v0.jsonl"))
    parser.add_argument("--target", type=Path, default=Path("data/scam_safety/repair-target-v1.jsonl"))
    parser.add_argument("--development", type=Path, default=Path("data/scam_safety/development-v1.jsonl"))
    parser.add_argument("--repair-curriculum", type=Path, default=Path("data/scam_safety/repair-curriculum-v1.jsonl"))
    parser.add_argument("--combined-curriculum", type=Path, default=Path("data/scam_safety/curriculum-v1.jsonl"))
    parser.add_argument("--evidence", type=Path, default=Path("artifacts/scam-safety/repair-authoring-v1.json"))
    args = parser.parse_args()
    result = asyncio.run(
        author_repair_bundle(
            args.plan,
            args.original_curriculum,
            args.original_development,
            args.target,
            args.development,
            args.repair_curriculum,
            args.combined_curriculum,
            args.evidence,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
