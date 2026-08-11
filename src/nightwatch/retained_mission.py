from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nightwatch.contracts import Stage
from nightwatch.journal import JournalEntry, append_stage

DEFAULT_CYCLE_ID = "nightwatch-v2-qualification"


@dataclass(frozen=True)
class MissionEntrySpec:
    stage: Stage
    payload: dict[str, object]


@dataclass(frozen=True)
class MissionBundle:
    cycle_id: str
    entries: tuple[MissionEntrySpec, ...]


def _read_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nested(mapping: dict[str, object], *keys: str) -> object:
    value: object = mapping
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"missing retained field: {'.'.join(keys)}")
        value = value[key]
    return value


def _candidate_training(report: dict[str, object], report_path: Path) -> dict[str, object]:
    artifact_name = _nested(report, "artifact_name")
    model_id = _nested(report, "training", "model_id")
    model_revision = _nested(report, "training", "model_revision")
    runtime = _nested(report, "training", "train_runtime")
    examples = _nested(report, "training", "examples")
    seed = _nested(report, "training", "seed")
    if not all(isinstance(value, str) and value for value in [artifact_name, model_id, model_revision]):
        raise ValueError(f"{report_path}: invalid candidate identity")
    return {
        "artifact_name": artifact_name,
        "model_id": model_id,
        "model_revision": model_revision,
        "training_runtime_seconds": runtime,
        "examples": examples,
        "seed": seed,
        "report_sha256": _sha256(report_path),
    }


def _candidate_evaluation(report: dict[str, object], report_path: Path) -> dict[str, object]:
    artifact_name = _nested(report, "artifact_name")
    assessment = _nested(report, "assessment")
    evaluation = _nested(report, "evaluation")
    if not isinstance(assessment, dict) or not isinstance(evaluation, dict):
        raise ValueError(f"{report_path}: invalid v2 evaluation")
    accepted = assessment.get("accepted")
    if not isinstance(accepted, bool):
        raise ValueError(f"{report_path}: assessment.accepted must be boolean")
    scores = evaluation.get("scores")
    label_recall = evaluation.get("label_recall")
    critical_misses = evaluation.get("critical_misses")
    invalid_case_ids = evaluation.get("invalid_case_ids")
    if not isinstance(scores, dict) or not isinstance(label_recall, dict):
        raise ValueError(f"{report_path}: evaluation metrics are malformed")
    if not isinstance(critical_misses, list) or not isinstance(invalid_case_ids, list):
        raise ValueError(f"{report_path}: evaluation safety fields are malformed")
    return {
        "artifact_name": artifact_name,
        "decision": "promoted" if accepted else "refused",
        "scores": scores,
        "regression_label_recall": label_recall.get("regression"),
        "critical_misses": critical_misses,
        "invalid_case_ids": invalid_case_ids,
        "reasons": assessment.get("reasons"),
        "report_sha256": _sha256(report_path),
    }


def build_retained_promotion_mission(
    *,
    cycle_id: str = DEFAULT_CYCLE_ID,
    curriculum_evidence_path: Path = Path("artifacts/v0-safety-augmentation-evidence.json"),
    curriculum_path: Path = Path("artifacts/v0-safety-augmented-curriculum.jsonl"),
    model_270_report_path: Path = Path(
        "artifacts/classifier-1395040c-1e98fdcf-74d932a468-dev-report.json"
    ),
    model_1b_report_path: Path = Path(
        "artifacts/classifier-1395040c-1e98fdcf-2f16394da7-dev-report.json"
    ),
    evidence_manifest_path: Path = Path("artifacts/evidence-audit-v2/manifest.json"),
    model_270_v2_report_path: Path = Path(
        "artifacts/evidence-audit-v2/reports/"
        "classifier-1395040c-1e98fdcf-74d932a468-dev-predictions-v2-report.json"
    ),
    model_1b_v2_report_path: Path = Path(
        "artifacts/evidence-audit-v2/reports/"
        "classifier-1395040c-1e98fdcf-2f16394da7-dev-predictions-v2-report.json"
    ),
) -> MissionBundle:
    curriculum_evidence = _read_object(curriculum_evidence_path)
    model_270_report = _read_object(model_270_report_path)
    model_1b_report = _read_object(model_1b_report_path)
    evidence_manifest = _read_object(evidence_manifest_path)
    model_270_v2 = _read_object(model_270_v2_report_path)
    model_1b_v2 = _read_object(model_1b_v2_report_path)

    curriculum_sha256 = _sha256(curriculum_path)
    if curriculum_evidence.get("output_sha256") != curriculum_sha256:
        raise ValueError("Gemini curriculum evidence does not match the retained curriculum bytes")
    if curriculum_evidence.get("teacher_model") != "gemini-3.6-flash":
        raise ValueError("retained curriculum was not generated by the required Gemini model")
    if evidence_manifest.get("adjudication_complete") is not True:
        raise ValueError("v2 evidence adjudication is incomplete")

    candidate_rescores = evidence_manifest.get("candidate_rescores")
    if not isinstance(candidate_rescores, list):
        raise ValueError("v2 manifest candidate rescores are malformed")
    promoted_rows = [
        row for row in candidate_rescores if isinstance(row, dict) and row.get("accepted") is True
    ]
    if len(promoted_rows) != 1:
        raise ValueError("v2 evidence must promote exactly one retained candidate")
    promoted_artifact = promoted_rows[0].get("artifact_name")
    if promoted_artifact != model_1b_v2.get("artifact_name"):
        raise ValueError("v2 manifest promotion does not match the retained 1B report")

    training_attempts = [
        _candidate_training(model_270_report, model_270_report_path),
        _candidate_training(model_1b_report, model_1b_report_path),
    ]
    evaluation_attempts = [
        _candidate_evaluation(model_270_v2, model_270_v2_report_path),
        _candidate_evaluation(model_1b_v2, model_1b_v2_report_path),
    ]
    if [attempt["artifact_name"] for attempt in training_attempts] != [
        attempt["artifact_name"] for attempt in evaluation_attempts
    ]:
        raise ValueError("training and v2 evaluation candidate identities do not match")
    if [attempt["decision"] for attempt in evaluation_attempts] != ["refused", "promoted"]:
        raise ValueError("retained mission must contain a refused 270M and promoted 1B candidate")

    original_safety = _nested(model_270_report, "dev_evaluation", "scores", "safety", "accuracy")
    original_assessment = _nested(model_270_report, "dev_assessment")
    promoted_evaluation = evaluation_attempts[1]
    promoted_training = training_attempts[1]
    entries = (
        MissionEntrySpec(
            Stage.CREATED,
            {
                "mission_kind": "retained_model_qualification",
                "subject": "small-model incident triage",
                "trigger": {
                    "type": "qualification_failure",
                    "artifact_name": training_attempts[0]["artifact_name"],
                    "safety_accuracy": original_safety,
                    "required_safety_accuracy": 0.9,
                },
                "evidence_mode": "retained_content_addressed_artifacts",
            },
        ),
        MissionEntrySpec(
            Stage.DIAGNOSED,
            {
                "actor": "deterministic_policy_analyzer",
                "finding": "candidate remained below the fixed safety floor",
                "assessment": original_assessment,
                "authorized_action": "generate one fixed safety curriculum, then escalate capacity",
                "forbidden_action": "weaken qualification thresholds",
            },
        ),
        MissionEntrySpec(
            Stage.CURRICULUM_READY,
            {
                "architect": {
                    "framework": "google_adk",
                    "model": curriculum_evidence["teacher_model"],
                    "generated_examples": curriculum_evidence["generated_examples"],
                },
                "curriculum_sha256": curriculum_sha256,
                "total_examples": curriculum_evidence["total_examples"],
                "maximum_similarity": curriculum_evidence["maximum_similarity"],
                "leakage_policy": "exact overlap denied; token Jaccard below 0.50",
            },
        ),
        MissionEntrySpec(
            Stage.TRAINED,
            {
                "executor": "modal",
                "attempts": training_attempts,
                "selection_policy": "fixed 270M intervention followed by one pinned 1B capacity test",
                "hyperparameter_search": False,
            },
        ),
        MissionEntrySpec(
            Stage.EVALUATED,
            {
                "evaluator": "deterministic_policy_v2",
                "attempts": evaluation_attempts,
                "evidence": {
                    "case_count": evidence_manifest["case_count"],
                    "adjudicated_disagreements": evidence_manifest[
                        "adjudicated_disagreement_count"
                    ],
                    "labels_changed": evidence_manifest["retained_labels_changed"],
                    "manifest_sha256": _sha256(evidence_manifest_path),
                },
                "retrained_after_adjudication": False,
            },
        ),
        MissionEntrySpec(
            Stage.PROMOTED,
            {
                "artifact_name": promoted_artifact,
                "model_id": promoted_training["model_id"],
                "model_revision": promoted_training["model_revision"],
                "qualified_under": "policy_v2",
                "deployment_status": "qualified_not_deployed",
                "scores": promoted_evaluation["scores"],
                "regression_label_recall": promoted_evaluation["regression_label_recall"],
                "critical_misses": promoted_evaluation["critical_misses"],
                "invalid_case_ids": promoted_evaluation["invalid_case_ids"],
                "promotion_authority": "deterministic_code_only",
            },
        ),
    )
    return MissionBundle(cycle_id=cycle_id, entries=entries)


def materialize_mission(
    mission: MissionBundle,
    write_stage: Callable[[str, Stage, dict[str, object]], JournalEntry | object],
) -> list[JournalEntry | object]:
    return [
        write_stage(mission.cycle_id, entry.stage, entry.payload) for entry in mission.entries
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize the retained Nightwatch v2 mission")
    parser.add_argument("--cycle-id", default=DEFAULT_CYCLE_ID)
    parser.add_argument("--backend", choices=("file", "firestore"), default="file")
    parser.add_argument("--output", type=Path, default=Path("artifacts/retained-mission.jsonl"))
    parser.add_argument("--project")
    args = parser.parse_args()
    mission = build_retained_promotion_mission(cycle_id=args.cycle_id)
    if args.backend == "firestore":
        from nightwatch.firestore_journal import FirestoreJournal

        journal = FirestoreJournal.from_default(project=args.project)
        entries = materialize_mission(mission, journal.append_stage)
    else:
        entries = materialize_mission(
            mission,
            lambda cycle_id, stage, payload: append_stage(
                args.output,
                cycle_id,
                stage,
                payload,
            ),
        )
    print(
        json.dumps(
            {
                "cycle_id": mission.cycle_id,
                "entry_count": len(entries),
                "terminal_stage": entries[-1].stage.value,
                "head_hash": entries[-1].entry_hash,
                "backend": args.backend,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
