from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from nightwatch.datasets import canonical_prompt
from nightwatch.scam_data_agent import MAX_TRAIN_EVAL_JACCARD, _jsonl, maximum_train_eval_jaccard
from nightwatch.scam_repair_data_agent import _author_family, _load_plan
from nightwatch.scam_safety import assert_no_scam_eval_leakage, load_scam_curriculum, load_scam_eval_cases


async def author_followup_curriculum(
    plan_path: Path,
    prior_curriculum_path: Path,
    development_path: Path,
    repair_path: Path,
    combined_path: Path,
    evidence_path: Path,
) -> dict[str, object]:
    if any(path.exists() for path in (repair_path, combined_path, evidence_path)):
        raise FileExistsError("refusing to overwrite retained follow-up repair evidence")
    wrapper, plan = _load_plan(plan_path)
    prior = load_scam_curriculum(prior_curriculum_path)
    development = load_scam_eval_cases(development_path)
    families = list(plan["repair_families"])
    repair_rows: list[dict[str, object]] = []
    similarity: dict[str, object] = {}
    for attempt in range(1, 4):
        batches = await asyncio.gather(
            *(
                _author_family(
                    family,
                    int(plan["examples_per_family"]),
                    f"followup_curriculum_pass_{attempt}",
                )
                for family in families
            )
        )
        candidate = [row for batch in batches for row in batch]
        messages = [canonical_prompt(str(row["message"])) for row in candidate]
        combined = [*prior, *candidate]
        similarity = maximum_train_eval_jaccard(
            combined,
            [
                {"message": case.message, "suite": case.suite.value, "expected_label": case.expected_label}
                for case in development
            ],
        )
        if len(messages) == len(set(messages)) and float(similarity["score"]) < MAX_TRAIN_EVAL_JACCARD:
            repair_rows = candidate
            break
    if not repair_rows:
        raise ValueError("follow-up curriculum failed duplicate or similarity checks")
    repair_output = [
        {key: row[key] for key in ("message", "label", "threat_family", "rationale")}
        for row in repair_rows
    ]
    combined_output = [*prior, *repair_output]
    repair_bytes = _jsonl(repair_output).encode()
    combined_bytes = _jsonl(combined_output).encode()
    repair_path.parent.mkdir(parents=True, exist_ok=True)
    repair_path.write_bytes(repair_bytes)
    combined_path.write_bytes(combined_bytes)
    combined = load_scam_curriculum(combined_path)
    assert_no_scam_eval_leakage(combined, development)
    evidence = {
        "schema_version": 1,
        "author_model": wrapper["author_model"],
        "source_candidate": wrapper["artifact_name"],
        "repair_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "development_sha256": hashlib.sha256(development_path.read_bytes()).hexdigest(),
        "prior_curriculum_sha256": hashlib.sha256(prior_curriculum_path.read_bytes()).hexdigest(),
        "repair_curriculum_sha256": hashlib.sha256(repair_bytes).hexdigest(),
        "combined_curriculum_sha256": hashlib.sha256(combined_bytes).hexdigest(),
        "repair_rows": len(repair_output),
        "combined_curriculum_rows": len(combined),
        "repair_families": families,
        "maximum_train_eval_token_jaccard": similarity,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description="Author an additive Nightwatch follow-up curriculum")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--prior-curriculum", type=Path, default=Path("data/scam_safety/curriculum-v1.jsonl"))
    parser.add_argument("--development", type=Path, default=Path("data/scam_safety/development-v1.jsonl"))
    parser.add_argument("--repair", type=Path, default=Path("data/scam_safety/repair-curriculum-v2.jsonl"))
    parser.add_argument("--combined", type=Path, default=Path("data/scam_safety/curriculum-v2.jsonl"))
    parser.add_argument("--evidence", type=Path, default=Path("artifacts/scam-safety/repair-authoring-v2.json"))
    args = parser.parse_args()
    result = asyncio.run(
        author_followup_curriculum(
            args.plan,
            args.prior_curriculum,
            args.development,
            args.repair,
            args.combined,
            args.evidence,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
