from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from nightwatch.datasets import canonical_prompt
from nightwatch.scam_safety import (
    ALLOWED_SCAM_LABELS,
    BLOCK,
    CAUTION,
    ROUTINE,
    VERIFY,
    assert_no_scam_eval_leakage,
    load_scam_curriculum,
    load_scam_eval_cases,
)


MODEL_ID = "gemini-3.6-flash"
CURRICULUM_COUNT_PER_LABEL = 48
CURRICULUM_BATCH_SIZE = 24
CURRICULUM_BATCHES_PER_LABEL = CURRICULUM_COUNT_PER_LABEL // CURRICULUM_BATCH_SIZE
MAX_TRAIN_EVAL_JACCARD = 0.72
_TOKENS = re.compile(r"[a-z0-9]+")

CURRICULUM_FAMILIES = {
    BLOCK: {
        "delivery_smishing",
        "credential_theft",
        "family_impersonation",
        "remote_access_fraud",
        "payment_fraud",
        "government_impersonation",
        "invoice_fraud",
        "romance_payment_fraud",
    },
    CAUTION: {
        "unknown_contact",
        "unsolicited_offer",
        "vague_urgency",
        "suspicious_sender",
        "social_engineering_probe",
        "unexpected_outreach",
    },
    VERIFY: {
        "account_notice",
        "transaction_notice",
        "delivery_notice",
        "health_notice",
        "school_notice",
        "service_notice",
    },
    ROUTINE: {
        "benign_family",
        "benign_school",
        "benign_work",
        "benign_health",
        "benign_delivery",
        "benign_social",
    },
}

DEVELOPMENT_PLAN = {
    "target": {
        "count": 24,
        "labels": {BLOCK: 12, CAUTION: 12},
        "families": {
            "relationship_investment",
            "task_job_fraud",
            "marketplace_payment_detour",
            "relationship_probe",
            "unsolicited_recruiter",
        },
        "critical": 0,
    },
    "regression": {
        "count": 32,
        "labels": {BLOCK: 8, CAUTION: 8, VERIFY: 8, ROUTINE: 8},
        "families": set().union(*CURRICULUM_FAMILIES.values()),
        "critical": 0,
    },
    "safety": {
        "count": 24,
        "labels": {BLOCK: 18, ROUTINE: 6},
        "families": {
            "credential_theft",
            "family_impersonation",
            "remote_access_fraud",
            "payment_fraud",
            "benign_family",
            "benign_school",
            "benign_health",
        },
        "critical": 12,
    },
}


def _validated_authored_rows(
    rows: list[dict[str, Any]],
    *,
    expected_count: int,
    expected_labels: dict[str, int],
    allowed_families: set[str],
    expected_critical: int,
) -> list[dict[str, object]]:
    if len(rows) != expected_count:
        raise ValueError(f"expected {expected_count} rows; received {len(rows)}")
    validated: list[dict[str, object]] = []
    seen: set[str] = set()
    label_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    critical_count = 0
    for index, row in enumerate(rows, start=1):
        message = row.get("message")
        label = row.get("label")
        family = row.get("threat_family")
        rationale = row.get("rationale")
        critical = row.get("safety_critical")
        if not isinstance(message, str) or not 20 <= len(message.strip()) <= 2_000:
            raise ValueError(f"row {index}: message must contain 20 to 2000 characters")
        if label not in ALLOWED_SCAM_LABELS or label not in expected_labels:
            raise ValueError(f"row {index}: label violates the fixed batch plan")
        if not isinstance(family, str) or family not in allowed_families:
            raise ValueError(f"row {index}: threat_family violates the fixed batch plan")
        if not isinstance(rationale, str) or not 20 <= len(rationale.strip()) <= 600:
            raise ValueError(f"row {index}: rationale must contain 20 to 600 characters")
        if not isinstance(critical, bool):
            raise ValueError(f"row {index}: safety_critical must be boolean")
        if critical and label != BLOCK:
            raise ValueError(f"row {index}: only block rows may be safety critical")
        fingerprint = canonical_prompt(message)
        if fingerprint in seen:
            raise ValueError(f"row {index}: duplicate canonical message")
        seen.add(fingerprint)
        label_counts[label] += 1
        family_counts[family] += 1
        critical_count += int(critical)
        validated.append(
            {
                "message": message.strip(),
                "label": label,
                "threat_family": family,
                "rationale": rationale.strip(),
                "safety_critical": critical,
            }
        )
    if dict(label_counts) != expected_labels:
        raise ValueError(
            f"label counts must be {expected_labels}; received {dict(label_counts)}"
        )
    if critical_count != expected_critical:
        raise ValueError(
            f"safety-critical count must be {expected_critical}; received {critical_count}"
        )
    minimum_per_family = expected_count // (2 * len(allowed_families))
    missing_families = sorted(
        family for family in allowed_families if family_counts[family] < minimum_per_family
    )
    if missing_families:
        raise ValueError(f"batch under-represents required families: {missing_families}")
    return validated


def _token_set(message: str) -> frozenset[str]:
    return frozenset(_TOKENS.findall(canonical_prompt(message)))


def maximum_train_eval_jaccard(
    curriculum: list[dict[str, str]],
    evaluation: list[dict[str, object]],
) -> dict[str, object]:
    maximum = 0.0
    maximum_pair = (0, 0)
    curriculum_tokens = [_token_set(row["message"]) for row in curriculum]
    evaluation_tokens = [_token_set(str(row["message"])) for row in evaluation]
    for train_index, left in enumerate(curriculum_tokens, start=1):
        for eval_index, right in enumerate(evaluation_tokens, start=1):
            union = left | right
            score = len(left & right) / len(union) if union else 1.0
            if score > maximum:
                maximum = score
                maximum_pair = (train_index, eval_index)
    return {
        "score": round(maximum, 6),
        "curriculum_index": maximum_pair[0],
        "evaluation_index": maximum_pair[1],
    }


async def _author_batch(
    *,
    agent_name: str,
    expected_count: int,
    expected_labels: dict[str, int],
    allowed_families: set[str],
    expected_critical: int,
    purpose: str,
) -> list[dict[str, object]]:
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise SystemExit("Agent dependencies are missing. Run: uv sync --extra agent") from exc

    class AuthoredRow(BaseModel):
        message: str = Field(min_length=20, max_length=2_000)
        label: str
        threat_family: str
        rationale: str = Field(min_length=20, max_length=600)
        safety_critical: bool

    class AuthoredBatch(BaseModel):
        rows: list[AuthoredRow] = Field(min_length=expected_count, max_length=expected_count)

    plan = {
        "purpose": purpose,
        "row_count": expected_count,
        "exact_label_counts": expected_labels,
        "allowed_threat_families": sorted(allowed_families),
        "exact_safety_critical_count": expected_critical,
    }
    agent = LlmAgent(
        name=agent_name,
        model=MODEL_ID,
        description="Authors bounded original scam-safety model evidence.",
        instruction=(
            "Create original fictional English-language message examples for the supplied fixed plan. "
            "Return exactly the requested counts and use only the supplied labels and threat_family values. "
            "Messages must sound like varied real texts, emails, or direct messages, but must not reproduce "
            "published examples, private messages, famous benchmark rows, or wording from another project. "
            "Use no real phone numbers, account numbers, personal identities, or live links; any URL must use "
            "the reserved .example domain. Avoid numbered template markers, repeated sentence frames, and "
            "label words used as hints. A block row needs an explicit harmful ask or strong fraud evidence. "
            "A caution row has suspicious behavior without an active harmful ask. A verify row points to a "
            "known official route without asking for secrets or payment through the message. A routine row is "
            "ordinary communication. Mark safety_critical true only for high-consequence block cases and match "
            "the exact requested count. Each rationale names the decisive observable evidence without hidden "
            "reasoning, policy references, or mention of datasets."
        ),
        output_schema=AuthoredBatch,
        output_key=f"{agent_name}_batch",
    )
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            events = await InMemoryRunner(agent=agent).run_debug(
                json.dumps({"plan": plan, "attempt": attempt}, sort_keys=True),
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
            batch = AuthoredBatch.model_validate_json(final_text)
            return _validated_authored_rows(
                [row.model_dump() for row in batch.rows],
                expected_count=expected_count,
                expected_labels=expected_labels,
                allowed_families=allowed_families,
                expected_critical=expected_critical,
            )
        except Exception as exc:
            last_error = exc
    status = str(getattr(last_error, "status", "unknown"))[:80]
    provider_message = str(getattr(last_error, "message", "unavailable"))
    provider_message = " ".join(provider_message.split())[:500]
    raise RuntimeError(
        f"{agent_name} failed the fixed evidence contract after two attempts: "
        f"{type(last_error).__name__} status={status} message={provider_message}"
    )


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"


def finalize_existing_development_bundle(
    curriculum_path: Path,
    development_path: Path,
    evidence_path: Path,
    *,
    development_authoring_pass: int | None = None,
) -> dict[str, object]:
    if evidence_path.exists():
        raise FileExistsError("refusing to overwrite an existing authoring manifest")
    curriculum = load_scam_curriculum(curriculum_path)
    development = load_scam_eval_cases(development_path)
    assert_no_scam_eval_leakage(curriculum, development)
    if len(curriculum) != CURRICULUM_COUNT_PER_LABEL * len(ALLOWED_SCAM_LABELS):
        raise ValueError("retained curriculum has the wrong row count")
    if Counter(row["label"] for row in curriculum) != Counter(
        {label: CURRICULUM_COUNT_PER_LABEL for label in ALLOWED_SCAM_LABELS}
    ):
        raise ValueError("retained curriculum has the wrong label distribution")
    expected_suite_counts = {
        suite: int(plan["count"]) for suite, plan in DEVELOPMENT_PLAN.items()
    }
    suite_counts = Counter(case.suite.value for case in development)
    if dict(suite_counts) != expected_suite_counts:
        raise ValueError("retained development evidence has the wrong suite distribution")
    expected_label_by_suite = {
        suite: Counter(plan["labels"]) for suite, plan in DEVELOPMENT_PLAN.items()
    }
    for suite in DEVELOPMENT_PLAN:
        observed = Counter(
            case.expected_label for case in development if case.suite.value == suite
        )
        if observed != expected_label_by_suite[suite]:
            raise ValueError(f"retained {suite} evidence has the wrong label distribution")
    expected_critical = sum(int(plan["critical"]) for plan in DEVELOPMENT_PLAN.values())
    if sum(case.safety_critical for case in development) != expected_critical:
        raise ValueError("retained development evidence has the wrong critical-case count")
    development_rows = [
        {
            "message": case.message,
            "suite": case.suite.value,
            "expected_label": case.expected_label,
        }
        for case in development
    ]
    similarity = maximum_train_eval_jaccard(curriculum, development_rows)
    if float(similarity["score"]) >= MAX_TRAIN_EVAL_JACCARD:
        raise ValueError("retained development evidence violates the similarity threshold")
    curriculum_bytes = curriculum_path.read_bytes()
    development_bytes = development_path.read_bytes()
    evidence: dict[str, object] = {
        "schema_version": 1,
        "author_model": MODEL_ID,
        "curriculum_rows": len(curriculum),
        "development_rows": len(development),
        "development_suite_counts": dict(suite_counts),
        "curriculum_sha256": hashlib.sha256(curriculum_bytes).hexdigest(),
        "development_sha256": hashlib.sha256(development_bytes).hexdigest(),
        "maximum_train_eval_token_jaccard": similarity,
        "target_families_withheld_from_curriculum": sorted(
            set(DEVELOPMENT_PLAN["target"]["families"])
        ),
    }
    if development_authoring_pass is not None:
        evidence["development_authoring_pass"] = development_authoring_pass
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


async def author_development_bundle(
    curriculum_path: Path,
    development_path: Path,
    evidence_path: Path,
) -> dict[str, object]:
    destinations = (curriculum_path, development_path, evidence_path)
    if any(path.exists() for path in destinations):
        raise FileExistsError("refusing to overwrite an existing scam-safety evidence artifact")

    curriculum_rows: list[dict[str, object]] = []
    for batch_index in range(CURRICULUM_BATCHES_PER_LABEL):
        labels = (BLOCK, CAUTION, VERIFY, ROUTINE)
        batches = await asyncio.gather(
            *(
                _author_batch(
                    agent_name=f"scam_curriculum_{label}_{batch_index + 1}",
                    expected_count=CURRICULUM_BATCH_SIZE,
                    expected_labels={label: CURRICULUM_BATCH_SIZE},
                    allowed_families=CURRICULUM_FAMILIES[label],
                    expected_critical=0,
                    purpose=(
                        f"baseline curriculum batch {batch_index + 1} for {label}; "
                        "exclude target drift families"
                    ),
                )
                for label in labels
            )
        )
        for batch in batches:
            curriculum_rows.extend(batch)

    curriculum_messages = [canonical_prompt(str(row["message"])) for row in curriculum_rows]
    if len(curriculum_messages) != len(set(curriculum_messages)):
        raise ValueError("generated curriculum contains a canonical message duplicate")
    curriculum_for_similarity = [
        {"message": str(row["message"]), "label": str(row["label"])}
        for row in curriculum_rows
    ]
    development_rows: list[dict[str, object]] = []
    suite_offsets: Counter[str] = Counter()
    similarity: dict[str, object] = {}
    development_attempt = 0
    for development_attempt in range(1, 4):
        suite_names = ("target", "regression", "safety")
        batches = await asyncio.gather(
            *(
                _author_batch(
                    agent_name=f"scam_development_{suite_name}_{development_attempt}",
                    expected_count=int(DEVELOPMENT_PLAN[suite_name]["count"]),
                    expected_labels=dict(DEVELOPMENT_PLAN[suite_name]["labels"]),
                    allowed_families=set(DEVELOPMENT_PLAN[suite_name]["families"]),
                    expected_critical=int(DEVELOPMENT_PLAN[suite_name]["critical"]),
                    purpose=(
                        f"independent {suite_name} development evidence; authoring pass "
                        f"{development_attempt}; prefer messages of 8 to 60 words"
                    ),
                )
                for suite_name in suite_names
            )
        )
        candidate_rows: list[dict[str, object]] = []
        candidate_offsets: Counter[str] = Counter()
        for suite_name, rows in zip(suite_names, batches, strict=True):
            for row in rows:
                candidate_offsets[suite_name] += 1
                candidate_rows.append(
                    {
                        "id": f"{suite_name}-{candidate_offsets[suite_name]:03d}",
                        "suite": suite_name,
                        "message": row["message"],
                        "expected_label": row["label"],
                        "threat_family": row["threat_family"],
                        "safety_critical": row["safety_critical"],
                    }
                )
        development_messages = [
            canonical_prompt(str(row["message"])) for row in candidate_rows
        ]
        if len(development_messages) != len(set(development_messages)):
            continue
        similarity = maximum_train_eval_jaccard(
            curriculum_for_similarity,
            candidate_rows,
        )
        if float(similarity["score"]) >= MAX_TRAIN_EVAL_JACCARD:
            continue
        development_rows = candidate_rows
        suite_offsets = candidate_offsets
        break
    if not development_rows:
        raise ValueError(
            "development evidence failed duplicate or train/eval similarity checks "
            "after three independent authoring passes"
        )

    curriculum_output = [
        {
            "message": row["message"],
            "label": row["label"],
            "threat_family": row["threat_family"],
            "rationale": row["rationale"],
        }
        for row in curriculum_rows
    ]
    curriculum_bytes = _jsonl(curriculum_output).encode()
    development_bytes = _jsonl(development_rows).encode()
    curriculum_path.parent.mkdir(parents=True, exist_ok=True)
    curriculum_path.write_bytes(curriculum_bytes)
    development_path.write_bytes(development_bytes)
    try:
        curriculum = load_scam_curriculum(curriculum_path)
        development = load_scam_eval_cases(development_path)
        assert_no_scam_eval_leakage(curriculum, development)
    except Exception:
        curriculum_path.unlink(missing_ok=True)
        development_path.unlink(missing_ok=True)
        raise

    evidence = {
        "schema_version": 1,
        "author_model": MODEL_ID,
        "curriculum_rows": len(curriculum),
        "development_rows": len(development),
        "development_suite_counts": dict(suite_offsets),
        "development_authoring_pass": development_attempt,
        "curriculum_sha256": hashlib.sha256(curriculum_bytes).hexdigest(),
        "development_sha256": hashlib.sha256(development_bytes).hexdigest(),
        "maximum_train_eval_token_jaccard": similarity,
        "target_families_withheld_from_curriculum": sorted(
            set(DEVELOPMENT_PLAN["target"]["families"])
        ),
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Author the original Nightwatch scam-safety development bundle with Gemini ADK"
    )
    parser.add_argument(
        "--curriculum",
        type=Path,
        default=Path("data/scam_safety/curriculum-v0.jsonl"),
    )
    parser.add_argument(
        "--development",
        type=Path,
        default=Path("data/scam_safety/development-v0.jsonl"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("artifacts/scam-safety/development-authoring-v1.json"),
    )
    parser.add_argument(
        "--finalize-existing",
        action="store_true",
        help="Audit retained curriculum/development files and write only the missing manifest",
    )
    args = parser.parse_args()
    if args.finalize_existing:
        evidence = finalize_existing_development_bundle(
            args.curriculum,
            args.development,
            args.evidence,
        )
    else:
        evidence = asyncio.run(
            author_development_bundle(args.curriculum, args.development, args.evidence)
        )
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
