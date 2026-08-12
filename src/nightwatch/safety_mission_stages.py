from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from nightwatch.contracts import Stage
from nightwatch.datasets import load_eval_cases, load_predictions
from nightwatch.evaluation import evaluate
from nightwatch.journal import JournalEntry, JournalError
from nightwatch.mission_orchestrator import MissionManifest
from nightwatch.safety_curriculum_agent import MODEL_ID, generate
from nightwatch.stage_artifacts import StageArtifact
from nightwatch.v0 import V0_POLICY_V2, assess_v0


class StageArtifactStore(Protocol):
    def read(
        self,
        cycle_id: str,
        stage: Stage,
        manifest_id: str,
    ) -> StageArtifact | None: ...

    def create(
        self,
        cycle_id: str,
        stage: Stage,
        manifest_id: str,
        payload: dict[str, Any],
    ) -> StageArtifact: ...


class TrainingStage(Protocol):
    def run(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]: ...


CurriculumGenerator = Callable[
    [Path, Path, Path],
    tuple[str, dict[str, Any]],
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise JournalError(f"{path}: invalid JSON evidence") from exc
    if not isinstance(value, dict):
        raise JournalError(f"{path}: expected an evidence object")
    return value


def generate_safety_curriculum(
    base_path: Path,
    development_path: Path,
    frozen_path: Path,
) -> tuple[str, dict[str, Any]]:
    """Run the real ADK agent and return private evidence for immutable storage."""

    with tempfile.TemporaryDirectory(prefix="nightwatch-curriculum-") as temporary:
        root = Path(temporary)
        output_path = root / "curriculum.jsonl"
        evidence_path = root / "generation-evidence.json"
        asyncio.run(
            generate(
                base_path,
                development_path,
                frozen_path,
                output_path,
                evidence_path,
            )
        )
        return output_path.read_text(encoding="utf-8"), _read_object(evidence_path)


class SafetyQualificationStageExecutor:
    """Real bounded stages before training; no arbitrary paths enter this class."""

    def __init__(
        self,
        artifact_store: StageArtifactStore,
        *,
        baseline_report_path: Path = Path(
            "artifacts/classifier-1395040c-1e98fdcf-74d932a468-dev-report.json"
        ),
        base_curriculum_path: Path = Path("artifacts/v0-curriculum.jsonl"),
        development_evidence_path: Path = Path("artifacts/v0-dev.jsonl"),
        frozen_evidence_path: Path = Path("data/eval/frozen.jsonl"),
        v2_evidence_path: Path = Path("artifacts/evidence-audit-v2/development.jsonl"),
        v2_manifest_path: Path = Path("artifacts/evidence-audit-v2/manifest.json"),
        curriculum_generator: CurriculumGenerator = generate_safety_curriculum,
        training_stage: TrainingStage | None = None,
    ) -> None:
        self._artifacts = artifact_store
        self._baseline_report_path = baseline_report_path
        self._base_curriculum_path = base_curriculum_path
        self._development_evidence_path = development_evidence_path
        self._frozen_evidence_path = frozen_evidence_path
        self._v2_evidence_path = v2_evidence_path
        self._v2_manifest_path = v2_manifest_path
        self._curriculum_generator = curriculum_generator
        self._training_stage = training_stage

    @staticmethod
    def _journal_payload(artifact: StageArtifact) -> dict[str, Any]:
        value = artifact.payload.get("journal_payload")
        if not isinstance(value, dict):
            raise JournalError("stage artifact is missing its journal projection")
        if "artifact_uri" in value or "artifact_sha256" in value:
            raise JournalError("stored journal projection may not override artifact identity")
        return {
            "manifest_id": artifact.manifest_id,
            "artifact_uri": artifact.uri,
            "artifact_sha256": artifact.sha256,
            **value,
        }

    def _existing(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
    ) -> dict[str, Any] | None:
        artifact = self._artifacts.read(cycle_id, stage, manifest.manifest_id)
        return self._journal_payload(artifact) if artifact else None

    def _create(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        private_payload: dict[str, Any],
    ) -> dict[str, Any]:
        artifact = self._artifacts.create(
            cycle_id,
            stage,
            manifest.manifest_id,
            private_payload,
        )
        return self._journal_payload(artifact)

    def execute(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        entries: tuple[JournalEntry, ...],
    ) -> dict[str, Any]:
        existing = self._existing(cycle_id, stage, manifest)
        if existing is not None:
            return existing
        if stage is Stage.DIAGNOSED:
            return self._diagnose(cycle_id, manifest)
        if stage is Stage.CURRICULUM_READY:
            return self._build_curriculum(cycle_id, manifest)
        if stage is Stage.TRAINED and self._training_stage is not None:
            return self._training_stage.run(cycle_id, manifest)
        if stage is Stage.EVALUATED:
            return self._evaluate(cycle_id, manifest)
        if stage in {Stage.PROMOTED, Stage.REJECTED}:
            return self._finalize(cycle_id, stage, manifest, entries)
        raise JournalError(f"real stage executor is not wired for {stage.value!r} yet")

    def _diagnose(
        self,
        cycle_id: str,
        manifest: MissionManifest,
    ) -> dict[str, Any]:
        report = _read_object(self._baseline_report_path)
        try:
            artifact_name = report["artifact_name"]
            safety = report["dev_evaluation"]["scores"]["safety"]
            accuracy = safety["accuracy"]
            correct = safety["correct"]
            total = safety["total"]
            assessment = report["dev_assessment"]
        except (KeyError, TypeError) as exc:
            raise JournalError("baseline report is missing required diagnosis evidence") from exc
        if (
            artifact_name != manifest.trigger_artifact_name
            or accuracy != manifest.observed_safety_accuracy
            or not isinstance(assessment, dict)
            or assessment.get("accepted") is not False
        ):
            raise JournalError("baseline report does not match the approved mission trigger")
        projection = {
            "actor": "deterministic_policy_analyzer",
            "finding": (
                f"candidate passed {correct}/{total} safety cases; "
                f"{accuracy:.3f} remains below the {manifest.required_safety_accuracy:.3f} floor"
            ),
            "assessment": assessment,
            "authorized_action": "generate one fixed safety curriculum, then train one pinned 270M candidate",
            "forbidden_action": "weaken qualification thresholds or expose retained prompts",
            "source_report_sha256": _sha256(self._baseline_report_path),
        }
        return self._create(
            cycle_id,
            Stage.DIAGNOSED,
            manifest,
            {"journal_payload": projection, "source_report": report},
        )

    def _build_curriculum(
        self,
        cycle_id: str,
        manifest: MissionManifest,
    ) -> dict[str, Any]:
        curriculum_jsonl, evidence = self._curriculum_generator(
            self._base_curriculum_path,
            self._development_evidence_path,
            self._frozen_evidence_path,
        )
        curriculum_bytes = curriculum_jsonl.encode("utf-8")
        curriculum_sha256 = hashlib.sha256(curriculum_bytes).hexdigest()
        if (
            not curriculum_jsonl.strip()
            or evidence.get("teacher_model") != MODEL_ID
            or evidence.get("output_sha256") != curriculum_sha256
            or evidence.get("generated_examples") != 32
            or not isinstance(evidence.get("maximum_similarity"), dict)
        ):
            raise JournalError("Gemini curriculum evidence failed its fixed contract")
        projection = {
            "architect": {
                "framework": "google_adk",
                "model": MODEL_ID,
                "generated_examples": evidence["generated_examples"],
            },
            "curriculum_sha256": curriculum_sha256,
            "total_examples": evidence.get("total_examples"),
            "maximum_similarity": evidence["maximum_similarity"],
            "leakage_policy": "exact overlap denied; token Jaccard below 0.50",
            "input_digests": {
                "base_curriculum": _sha256(self._base_curriculum_path),
                "development_evidence": _sha256(self._development_evidence_path),
                "frozen_evidence": _sha256(self._frozen_evidence_path),
            },
        }
        return self._create(
            cycle_id,
            Stage.CURRICULUM_READY,
            manifest,
            {
                "journal_payload": projection,
                "curriculum_jsonl": curriculum_jsonl,
                "generation_evidence": evidence,
            },
        )

    def _evaluate(
        self,
        cycle_id: str,
        manifest: MissionManifest,
    ) -> dict[str, Any]:
        trained = self._artifacts.read(cycle_id, Stage.TRAINED, manifest.manifest_id)
        if trained is None:
            raise JournalError("evaluation cannot start before immutable training evidence exists")
        modal_result = trained.payload.get("modal_result")
        if not isinstance(modal_result, dict):
            raise JournalError("training artifact is missing the Modal result")
        predictions_jsonl = modal_result.get("predictions_jsonl")
        artifact_name = modal_result.get("artifact_name")
        config = modal_result.get("config")
        if (
            not isinstance(predictions_jsonl, str)
            or not predictions_jsonl.strip()
            or not isinstance(artifact_name, str)
            or not isinstance(config, dict)
            or config.get("model_id") != manifest.model_id
            or config.get("model_revision") != manifest.model_revision
        ):
            raise JournalError("training artifact does not match the approved candidate")

        with tempfile.TemporaryDirectory(prefix="nightwatch-evaluation-") as temporary:
            predictions_path = Path(temporary) / "predictions.jsonl"
            predictions_path.write_text(predictions_jsonl, encoding="utf-8")
            report = evaluate(
                artifact_name,
                load_eval_cases(self._v2_evidence_path),
                load_predictions(predictions_path),
            )
        assessment = assess_v0(report, policy=V0_POLICY_V2)
        evidence_manifest = _read_object(self._v2_manifest_path)
        if (
            evidence_manifest.get("evidence_version") != "v2"
            or evidence_manifest.get("adjudication_complete") is not True
        ):
            raise JournalError("policy-v2 evidence manifest is not complete")
        evaluation = report.to_dict()
        projection = {
            "accepted": assessment.accepted,
            "evaluator": "deterministic_policy_v2",
            "attempts": [
                {
                    "artifact_name": artifact_name,
                    "decision": "qualified" if assessment.accepted else "refused",
                    "scores": evaluation["scores"],
                    "reasons": list(assessment.reasons),
                }
            ],
            "evidence": {
                "case_count": evidence_manifest.get("case_count"),
                "adjudicated_disagreements": evidence_manifest.get(
                    "adjudicated_disagreement_count"
                ),
                "labels_changed": evidence_manifest.get("retained_labels_changed"),
                "manifest_sha256": _sha256(self._v2_manifest_path),
            },
            "retrained_after_adjudication": True,
        }
        return self._create(
            cycle_id,
            Stage.EVALUATED,
            manifest,
            {
                "journal_payload": projection,
                "evaluation_report": evaluation,
                "assessment": assessment.to_dict(),
                "prediction_sha256": hashlib.sha256(predictions_jsonl.encode()).hexdigest(),
            },
        )

    def _finalize(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        entries: tuple[JournalEntry, ...],
    ) -> dict[str, Any]:
        if not entries or entries[-1].stage is not Stage.EVALUATED:
            raise JournalError("terminal decision requires an evaluated journal entry")
        accepted = entries[-1].payload.get("accepted")
        if accepted is not (stage is Stage.PROMOTED):
            raise JournalError("terminal stage conflicts with deterministic evaluation")
        evaluated = self._artifacts.read(cycle_id, Stage.EVALUATED, manifest.manifest_id)
        trained = self._artifacts.read(cycle_id, Stage.TRAINED, manifest.manifest_id)
        if evaluated is None or trained is None:
            raise JournalError("terminal decision is missing immutable evidence")
        evaluation = evaluated.payload.get("evaluation_report")
        assessment = evaluated.payload.get("assessment")
        modal_result = trained.payload.get("modal_result")
        if not all(isinstance(value, dict) for value in (evaluation, assessment, modal_result)):
            raise JournalError("terminal evidence is malformed")
        artifact_name = modal_result.get("artifact_name")
        projection = {
            "outcome": "qualified" if accepted else "refused",
            "artifact_name": artifact_name,
            "model_id": manifest.model_id,
            "model_revision": manifest.model_revision,
            "qualified_under": "policy_v2",
            "deployment_status": "qualified_not_deployed" if accepted else "refused_not_deployed",
            "scores": evaluation.get("scores"),
            "regression_label_recall": (
                evaluation.get("label_recall", {}).get("regression")
                if isinstance(evaluation.get("label_recall"), dict)
                else None
            ),
            "critical_misses": evaluation.get("critical_misses"),
            "invalid_case_ids": evaluation.get("invalid_case_ids"),
            "reasons": assessment.get("reasons"),
            "promotion_authority": "deterministic_code_only",
        }
        return self._create(
            cycle_id,
            stage,
            manifest,
            {"journal_payload": projection},
        )
