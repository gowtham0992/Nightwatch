from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nightwatch.contracts import Stage
from nightwatch.firestore_journal import MAX_MISSION_ENTRIES, validate_cycle_id
from nightwatch.journal import ALLOWED_TRANSITIONS, GENESIS_HASH, JournalEntry, JournalError

PUBLIC_MISSION_ID = "nightwatch-v2-qualification"
LIVE_PUBLIC_MISSION_ID = "nightwatch-cloud-20260811-001"
JUDGE_LIVE_MISSION_ID = "nightwatch-live-89e73407c43d525c4bc19272"
PUBLIC_MISSION_IDS = frozenset(
    {PUBLIC_MISSION_ID, LIVE_PUBLIC_MISSION_ID, JUDGE_LIVE_MISSION_ID}
)
PUBLIC_IDEMPOTENCY_KEY = "public:nightwatch-v2-proof:isolated-v1"
PUBLIC_VERIFICATION_GRACE_MINUTES = 5
_HASH = re.compile(r"^[a-f0-9]{64}$")
_FORBIDDEN_KEYS = {
    "artifact_name",
    "artifact_uri",
    "baseline_artifact",
    "candidate_artifact",
    "curriculum_sha256",
    "development_sha256",
    "evidence_case_ids",
    "manifest_sha256",
    "modal_call_id",
    "model_revision",
    "report_sha256",
    "selected_artifact",
    "seed",
}
_PUBLIC_STAGE_PREFIX = (
    "created",
    "diagnosed",
    "curriculum_ready",
    "trained",
    "evaluated",
)
_ALLOWED_KEYS = {
    "accuracy",
    "accepted",
    "actor",
    "adjudicated_disagreements",
    "architect",
    "artifact_sha256",
    "attempts",
    "attempt",
    "authorized_action",
    "baseline",
    "benign_block",
    "block",
    "candidate",
    "case_count",
    "correct",
    "count",
    "critical_miss_count",
    "curriculum_rows",
    "cycle_id",
    "decision",
    "defer",
    "deployment_status",
    "deployment_authorized",
    "development",
    "development_suite_counts",
    "entries",
    "entry_count",
    "entry_hash",
    "evaluator",
    "evidence",
    "evidence_case_count",
    "executor",
    "finding",
    "failed_invariants",
    "forbidden_action",
    "framework",
    "frozen",
    "generated_examples",
    "head_hash",
    "headline",
    "hyperparameter_search",
    "invalid_prediction_count",
    "investigate",
    "labels_changed",
    "leakage_policy",
    "leakage_check",
    "label_recall",
    "limits",
    "macro_f1",
    "manifest_id",
    "maximum_gpu_minutes",
    "maximum_training_attempts",
    "minimum_safety_block_recall",
    "minimum_target_gain",
    "maximum_similarity",
    "mission_kind",
    "model",
    "model_id",
    "observed_error_count",
    "outcome",
    "overall_accuracy",
    "page_now",
    "payload",
    "previous_hash",
    "promotion_authority",
    "public_summary",
    "qualified_under",
    "regression",
    "regression_drop",
    "regression_label_recall",
    "repair_families",
    "reason_count",
    "reasons",
    "required_safety_accuracy",
    "retrained_after_adjudication",
    "routine",
    "safety",
    "safety_accuracy",
    "scores",
    "selection_policy",
    "stage",
    "subject",
    "target",
    "target_accuracy",
    "target_gain",
    "terminal",
    "timestamp",
    "token_jaccard",
    "total",
    "total_examples",
    "training_runtime_seconds",
    "runtime_seconds",
    "trigger",
    "type",
    "rate",
    "examples",
    "verify",
    "visibility",
}


def _required(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise JournalError(f"public projection source is missing {key}")
    return mapping[key]


def public_idempotency_key(cycle_id: str) -> str:
    validate_cycle_id(cycle_id)
    if cycle_id not in PUBLIC_MISSION_IDS:
        raise JournalError("public mission is not allowlisted")
    if cycle_id == PUBLIC_MISSION_ID:
        return PUBLIC_IDEMPOTENCY_KEY
    return f"public:{cycle_id}:proof:isolated-v1"


def public_verification_idempotency_key(cycle_id: str, requested_at: datetime) -> str:
    """Return one server-controlled public verification intent per UTC minute."""
    validate_cycle_id(cycle_id)
    if cycle_id not in PUBLIC_MISSION_IDS:
        raise JournalError("public mission is not allowlisted")
    if requested_at.tzinfo is None:
        raise JournalError("public verification time must include a timezone")
    minute = requested_at.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return f"public:{cycle_id}:proof:{minute.strftime('%Y%m%dT%H%MZ')}"


def _scores(attempt: dict[str, Any]) -> dict[str, Any]:
    scores = _required(attempt, "scores")
    if not isinstance(scores, dict):
        raise JournalError("public projection scores are malformed")
    return scores


def _public_score(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise JournalError("public scam score is malformed")
    return {
        "correct": _required(value, "correct"),
        "total": _required(value, "total"),
        "accuracy": _required(value, "accuracy"),
    }


def _public_scam_report(value: object, *, candidate: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise JournalError("public scam evaluation is malformed")
    scores = _required(value, "scores")
    label_recall = _required(value, "label_recall")
    benign_block = _required(value, "benign_block")
    if not all(isinstance(item, dict) for item in (scores, label_recall, benign_block)):
        raise JournalError("public scam evaluation aggregates are malformed")
    regression_recall = _required(label_recall, "regression")
    safety_recall = _required(label_recall, "safety")
    if not isinstance(regression_recall, dict) or not isinstance(safety_recall, dict):
        raise JournalError("public scam label recall is malformed")
    return {
        "candidate": candidate,
        "scores": {
            suite: _public_score(_required(scores, suite))
            for suite in ("target", "safety", "regression")
        },
        "label_recall": {
            "regression": {
                "routine": _public_score(_required(regression_recall, "routine"))
            },
            "safety": {"block": _public_score(_required(safety_recall, "block"))},
        },
        "benign_block": {
            "count": _required(benign_block, "count"),
            "total": _required(benign_block, "total"),
            "rate": _required(benign_block, "rate"),
        },
        "critical_miss_count": len(value.get("critical_misses", [])),
        "invalid_prediction_count": len(value.get("invalid_case_ids", [])),
    }


def _failed_invariants(decision: dict[str, Any]) -> list[str]:
    reasons = _required(decision, "reasons")
    if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
        raise JournalError("public scam decision reasons are malformed")
    prefixes = {
        "target gain ": "target_gain_below_floor",
        "regression drop ": "regression_accuracy_regressed",
        "safety block recall ": "safety_block_recall_below_floor",
        "benign block rate ": "benign_block_rate_exceeded",
        "benign block rate increased ": "benign_block_rate_regressed",
        "regression routine recall declined ": "routine_recall_regressed",
        "regression verify recall declined ": "verify_recall_regressed",
        "critical safety misses:": "critical_safety_miss",
        "prediction coverage mismatch:": "prediction_coverage_incomplete",
    }
    if decision.get("decision") == "promote":
        return []
    return list(
        dict.fromkeys(
            next(
                (
                    prefixes[prefix]
                    for prefix in sorted(prefixes, key=len, reverse=True)
                    if reason.startswith(prefix)
                ),
                "other_gate_invariant_failed",
            )
            for reason in reasons
        )
    )


def _public_scam_decision(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise JournalError("public scam decision is malformed")
    return {
        "decision": _required(value, "decision"),
        "failed_invariants": _failed_invariants(value),
        "target_gain": _required(value, "target_gain"),
        "regression_drop": _required(value, "regression_drop"),
    }


def _public_scam_payload(entry: JournalEntry) -> dict[str, Any]:
    payload = entry.payload
    common = {"public_summary": True}
    if entry.stage is Stage.CREATED:
        trigger = _required(payload, "trigger")
        candidate = _required(payload, "candidate")
        limits = _required(payload, "limits")
        if not all(isinstance(item, dict) for item in (trigger, candidate, limits)):
            raise JournalError("public scam creation evidence is malformed")
        return {
            **common,
            "mission_kind": _required(payload, "mission_kind"),
            "manifest_id": _required(payload, "manifest_id"),
            "subject": _required(payload, "subject"),
            "trigger": {
                "type": _required(trigger, "type"),
                "target_accuracy": _required(trigger, "target_accuracy"),
                "minimum_target_gain": _required(trigger, "minimum_target_gain"),
                "minimum_safety_block_recall": _required(trigger, "minimum_safety_block_recall"),
            },
            "candidate": {"model_id": _required(candidate, "model_id")},
            "limits": {
                "maximum_training_attempts": _required(limits, "maximum_training_attempts"),
                "maximum_gpu_minutes": _required(limits, "maximum_gpu_minutes"),
            },
            "deployment_authorized": _required(payload, "deployment_authorized"),
        }
    if entry.stage is Stage.DIAGNOSED:
        evidence_ids = _required(payload, "evidence_case_ids")
        if not isinstance(evidence_ids, list):
            raise JournalError("public scam diagnosis evidence is malformed")
        return {
            **common,
            "manifest_id": _required(payload, "manifest_id"),
            "actor": _required(payload, "actor"),
            "model": _required(payload, "model"),
            "headline": _required(payload, "headline"),
            "observed_error_count": _required(payload, "observed_error_count"),
            "evidence_case_count": len(evidence_ids),
            "repair_families": _required(payload, "repair_families"),
            "authorized_action": _required(payload, "authorized_action"),
            "forbidden_action": _required(payload, "forbidden_action"),
            "artifact_sha256": _required(payload, "artifact_sha256"),
        }
    if entry.stage is Stage.CURRICULUM_READY:
        return {
            **common,
            "manifest_id": _required(payload, "manifest_id"),
            "architect": _required(payload, "architect"),
            "repair_families": _required(payload, "repair_families"),
            "curriculum_rows": _required(payload, "curriculum_rows"),
            "development_suite_counts": _required(payload, "development_suite_counts"),
            "leakage_check": _required(payload, "leakage_check"),
            "artifact_sha256": _required(payload, "artifact_sha256"),
        }
    if entry.stage is Stage.TRAINED:
        attempts = _required(payload, "attempts")
        if not isinstance(attempts, list) or not all(isinstance(attempt, dict) for attempt in attempts):
            raise JournalError("public scam training attempts are malformed")
        return {
            **common,
            "manifest_id": _required(payload, "manifest_id"),
            "executor": _required(payload, "executor"),
            "attempts": [
                {
                    "candidate": f"candidate-{index:02d}",
                    "attempt": _required(attempt, "attempt"),
                    "runtime_seconds": _required(attempt, "runtime_seconds"),
                    "examples": _required(attempt, "examples"),
                }
                for index, attempt in enumerate(attempts, start=1)
            ],
            "selection_policy": _required(payload, "selection_policy"),
            "maximum_training_attempts": _required(payload, "maximum_training_attempts"),
            "maximum_gpu_minutes": _required(payload, "maximum_gpu_minutes"),
            "artifact_sha256": _required(payload, "artifact_sha256"),
        }
    if entry.stage is Stage.EVALUATED:
        return {
            **common,
            "manifest_id": _required(payload, "manifest_id"),
            "accepted": _required(payload, "accepted"),
            "evaluator": _required(payload, "evaluator"),
            "decision": _public_scam_decision(_required(payload, "decision")),
            "baseline": _public_scam_report(_required(payload, "baseline"), candidate="baseline"),
            "candidate": _public_scam_report(_required(payload, "candidate"), candidate="candidate-01"),
            "artifact_sha256": _required(payload, "artifact_sha256"),
        }
    if entry.stage in {Stage.PROMOTED, Stage.REJECTED}:
        critical_misses = _required(payload, "critical_misses")
        if not isinstance(critical_misses, list):
            raise JournalError("public scam terminal evidence is malformed")
        return {
            **common,
            "manifest_id": _required(payload, "manifest_id"),
            "outcome": _required(payload, "outcome"),
            "candidate": "candidate-01",
            "model_id": _required(payload, "model_id"),
            "qualified_under": _required(payload, "qualified_under"),
            "deployment_status": _required(payload, "deployment_status"),
            "scores": _required(payload, "scores"),
            "critical_miss_count": len(critical_misses),
            "decision": _public_scam_decision(_required(payload, "decision")),
            "promotion_authority": _required(payload, "promotion_authority"),
            "artifact_sha256": _required(payload, "artifact_sha256"),
        }
    raise JournalError(f"unsupported public scam stage: {entry.stage.value}")


def _public_payload(entry: JournalEntry) -> dict[str, Any]:
    if entry.cycle_id == JUDGE_LIVE_MISSION_ID:
        return _public_scam_payload(entry)
    payload = entry.payload
    if entry.stage is Stage.CREATED:
        trigger = _required(payload, "trigger")
        if not isinstance(trigger, dict):
            raise JournalError("public trigger is malformed")
        return {
            "public_summary": True,
            "mission_kind": "retained_model_qualification",
            "subject": _required(payload, "subject"),
            "trigger": {
                "candidate": "Gemma 3 270M",
                "safety_accuracy": _required(trigger, "safety_accuracy"),
                "required_safety_accuracy": _required(trigger, "required_safety_accuracy"),
            },
        }
    if entry.stage is Stage.DIAGNOSED:
        return {
            "public_summary": True,
            "actor": _required(payload, "actor"),
            "finding": _required(payload, "finding"),
            "authorized_action": _required(payload, "authorized_action"),
            "forbidden_action": _required(payload, "forbidden_action"),
        }
    if entry.stage is Stage.CURRICULUM_READY:
        similarity = _required(payload, "maximum_similarity")
        if not isinstance(similarity, dict):
            raise JournalError("public similarity evidence is malformed")
        return {
            "public_summary": True,
            "architect": _required(payload, "architect"),
            "total_examples": _required(payload, "total_examples"),
            "maximum_similarity": {
                split: {"token_jaccard": _required(value, "token_jaccard")}
                for split, value in similarity.items()
                if isinstance(value, dict)
            },
            "leakage_policy": _required(payload, "leakage_policy"),
        }
    if entry.stage is Stage.TRAINED:
        attempts = _required(payload, "attempts")
        if not isinstance(attempts, list):
            raise JournalError("public training attempts are malformed")
        return {
            "public_summary": True,
            "executor": _required(payload, "executor"),
            "attempts": [
                {
                    "model_id": _required(attempt, "model_id"),
                    "training_runtime_seconds": _required(
                        attempt, "training_runtime_seconds"
                    ),
                }
                for attempt in attempts
                if isinstance(attempt, dict)
            ],
            "selection_policy": _required(payload, "selection_policy"),
            "hyperparameter_search": _required(payload, "hyperparameter_search"),
        }
    if entry.stage is Stage.EVALUATED:
        attempts = _required(payload, "attempts")
        if not isinstance(attempts, list):
            raise JournalError("public evaluation attempts are malformed")
        projected_attempts = []
        for index, attempt in enumerate(attempts):
            if not isinstance(attempt, dict):
                raise JournalError("public evaluation attempt is malformed")
            projected_attempts.append(
                {
                    "candidate": "Gemma 3 270M" if index == 0 else "Gemma 3 1B",
                    "decision": _required(attempt, "decision"),
                    "scores": _scores(attempt),
                    "critical_miss_count": len(attempt.get("critical_misses", [])),
                }
            )
        evidence = _required(payload, "evidence")
        if not isinstance(evidence, dict):
            raise JournalError("public evaluation evidence is malformed")
        return {
            "public_summary": True,
            "evaluator": _required(payload, "evaluator"),
            "attempts": projected_attempts,
            "evidence": {
                "case_count": _required(evidence, "case_count"),
                "adjudicated_disagreements": _required(
                    evidence, "adjudicated_disagreements"
                ),
                "labels_changed": _required(evidence, "labels_changed"),
            },
            "retrained_after_adjudication": _required(
                payload, "retrained_after_adjudication"
            ),
        }
    if entry.stage is Stage.PROMOTED:
        return {
            "public_summary": True,
            "model_id": _required(payload, "model_id"),
            "qualified_under": _required(payload, "qualified_under"),
            "deployment_status": _required(payload, "deployment_status"),
            "scores": _required(payload, "scores"),
            "regression_label_recall": _required(payload, "regression_label_recall"),
            "critical_miss_count": len(_required(payload, "critical_misses")),
            "invalid_prediction_count": len(_required(payload, "invalid_case_ids")),
            "promotion_authority": _required(payload, "promotion_authority"),
        }
    if entry.stage is Stage.REJECTED:
        return {
            "public_summary": True,
            "decision": "rejected",
            "model_id": _required(payload, "model_id"),
            "qualified_under": _required(payload, "qualified_under"),
            "deployment_status": _required(payload, "deployment_status"),
            "scores": _required(payload, "scores"),
            "regression_label_recall": _required(payload, "regression_label_recall"),
            "critical_miss_count": len(_required(payload, "critical_misses")),
            "invalid_prediction_count": len(_required(payload, "invalid_case_ids")),
            "promotion_authority": _required(payload, "promotion_authority"),
            "reasons": _required(payload, "reasons"),
            "reason_count": len(payload.get("reasons", [])),
        }
    raise JournalError(f"unsupported public stage: {entry.stage.value}")


def build_public_snapshot(
    cycle_id: str,
    entries: list[JournalEntry],
) -> dict[str, Any]:
    validate_cycle_id(cycle_id)
    if cycle_id not in PUBLIC_MISSION_IDS:
        raise JournalError("public projection mission is not allowlisted")
    if not entries or len(entries) > MAX_MISSION_ENTRIES:
        raise JournalError("public projection entry coverage is invalid")
    expected_previous = GENESIS_HASH
    projected = []
    for entry in entries:
        if entry.cycle_id != cycle_id or entry.previous_hash != expected_previous:
            raise JournalError("public projection source chain is invalid")
        projected.append(
            {
                "cycle_id": cycle_id,
                "stage": entry.stage.value,
                "timestamp": entry.timestamp,
                "payload": _public_payload(entry),
                "previous_hash": entry.previous_hash,
                "entry_hash": entry.entry_hash,
            }
        )
        expected_previous = entry.entry_hash
    return {
        "visibility": "public_redacted",
        "cycle_id": cycle_id,
        "entry_count": len(projected),
        "head_hash": expected_previous,
        "terminal": not bool(ALLOWED_TRANSITIONS[entries[-1].stage]),
        "entries": projected,
    }


def _walk_public_keys(value: object) -> None:
    if isinstance(value, dict):
        forbidden = _FORBIDDEN_KEYS.intersection(value)
        if forbidden:
            raise JournalError(f"public snapshot contains forbidden fields: {sorted(forbidden)}")
        unexpected = set(value).difference(_ALLOWED_KEYS)
        if unexpected:
            raise JournalError(f"public snapshot contains unexpected fields: {sorted(unexpected)}")
        for child in value.values():
            _walk_public_keys(child)
    elif isinstance(value, list):
        for child in value:
            _walk_public_keys(child)


def validate_public_snapshot(
    value: object,
    *,
    expected_cycle_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("visibility") != "public_redacted":
        raise JournalError("public snapshot envelope is malformed")
    cycle_id = value.get("cycle_id")
    if cycle_id not in PUBLIC_MISSION_IDS or (
        expected_cycle_id is not None and cycle_id != expected_cycle_id
    ):
        raise JournalError("public snapshot mission identity is invalid")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) != len(_PUBLIC_STAGE_PREFIX) + 1:
        raise JournalError("public snapshot entry coverage is invalid")
    if value.get("entry_count") != len(entries):
        raise JournalError("public snapshot entry count is invalid")
    expected_previous = GENESIS_HASH
    terminal_stage = entries[-1].get("stage") if isinstance(entries[-1], dict) else None
    if terminal_stage not in {"promoted", "rejected"}:
        raise JournalError("public snapshot terminal stage is invalid")
    stages = (*_PUBLIC_STAGE_PREFIX, terminal_stage)
    for expected_stage, row in zip(stages, entries, strict=True):
        if (
            not isinstance(row, dict)
            or row.get("cycle_id") != cycle_id
            or row.get("stage") != expected_stage
            or row.get("previous_hash") != expected_previous
            or not isinstance(row.get("entry_hash"), str)
            or not _HASH.fullmatch(row["entry_hash"])
            or not isinstance(row.get("payload"), dict)
            or row["payload"].get("public_summary") is not True
        ):
            raise JournalError("public snapshot chain is malformed")
        expected_previous = row["entry_hash"]
    if value.get("head_hash") != expected_previous or value.get("terminal") is not True:
        raise JournalError("public snapshot head is invalid")
    _walk_public_keys(value)
    return value


def load_public_snapshot(
    path: Path,
    *,
    expected_cycle_id: str | None = None,
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JournalError("public snapshot could not be loaded") from exc
    return validate_public_snapshot(value, expected_cycle_id=expected_cycle_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Emit the redacted public snapshot from a verified Firestore mission"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--cycle-id", default=PUBLIC_MISSION_ID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from nightwatch.firestore_journal import FirestoreJournal

    journal = FirestoreJournal.from_default(project=args.project)
    snapshot = build_public_snapshot(args.cycle_id, journal.read_cycle(args.cycle_id))
    rendered = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
