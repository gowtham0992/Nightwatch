from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from nightwatch.contracts import Stage
from nightwatch.journal import JournalEntry, JournalError
from nightwatch.mission_orchestrator import MissionManifest
from nightwatch.scam_gate import build_scam_gate_record
from nightwatch.scam_repair_agent import (
    MODEL_ID as TEACHER_MODEL_ID,
    author_scam_repair_plan,
    build_scam_failure_packet,
    validate_scam_repair_plan,
)
from nightwatch.scam_repair_data_agent import author_repair_bundle
from nightwatch.scam_safety import (
    assert_no_scam_eval_leakage,
    load_scam_curriculum,
    load_scam_eval_cases,
    load_scam_mission,
)
from nightwatch.stage_artifacts import StageArtifact


class StageArtifactStore(Protocol):
    def read(
        self, cycle_id: str, stage: Stage, manifest_id: str
    ) -> StageArtifact | None: ...

    def create(
        self,
        cycle_id: str,
        stage: Stage,
        manifest_id: str,
        payload: dict[str, Any],
    ) -> StageArtifact: ...


class ScamTrainingCampaign(Protocol):
    def run(
        self,
        cycle_id: str,
        manifest: MissionManifest,
        curriculum_artifact: StageArtifact,
    ) -> dict[str, Any]: ...


Diagnostician = Callable[[dict[str, object]], dict[str, object]]
CurriculumArchitect = Callable[[dict[str, object]], dict[str, object]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose_with_gemini(packet: dict[str, object]) -> dict[str, object]:
    return asyncio.run(author_scam_repair_plan(packet))


def retained_verified_diagnosis(packet: dict[str, object]) -> dict[str, object]:
    """Load the immutable Gemini/ADK diagnosis and bind it to this trigger."""

    evidence = _json_file(
        Path(
            "artifacts/scam-safety/"
            "scam-v0-de1e6009-2d77e636-c0e947096d-repair-plan.json"
        )
    )
    if (
        evidence.get("author_model") != TEACHER_MODEL_ID
        or evidence.get("artifact_name") != packet.get("artifact_name")
        or evidence.get("source_hashes") != packet.get("source_hashes")
        or not isinstance(evidence.get("plan"), dict)
    ):
        raise JournalError("retained Gemini diagnosis does not match the approved trigger")
    return evidence["plan"]


def retained_verified_curriculum(_diagnosis_payload: dict[str, object]) -> dict[str, object]:
    """Return the final immutable curriculum earned by the bounded repair campaign."""

    return {
        "curriculum_jsonl": Path("data/scam_safety/curriculum-v5.jsonl").read_text(
            encoding="utf-8"
        ),
        "development_jsonl": Path("data/scam_safety/development-v1.jsonl").read_text(
            encoding="utf-8"
        ),
        "authoring_evidence": _json_file(
            Path("artifacts/scam-safety/repair-authoring-v5.json")
        ),
    }


def _json_file(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JournalError(f"invalid retained evidence: {path}") from exc
    if not isinstance(value, dict):
        raise JournalError(f"retained evidence must be an object: {path}")
    return value


class ScamSafetyStageExecutor:
    """Durable scam-safety lifecycle with a deterministic release boundary.

    Gemini may diagnose and author bounded training data. The training campaign
    may spend only the limits in the approved manifest. Neither component can
    select the terminal state; evaluation code recomputes that decision from
    predictions and the pinned gate contract.
    """

    def __init__(
        self,
        artifact_store: StageArtifactStore,
        *,
        mission_path: Path = Path("data/scam_safety/mission.json"),
        original_curriculum_path: Path = Path("data/scam_safety/curriculum-v0.jsonl"),
        original_development_path: Path = Path("data/scam_safety/development-v0.jsonl"),
        baseline_predictions_path: Path = Path(
            "artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-development-predictions.jsonl"
        ),
        baseline_report_path: Path = Path(
            "artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-development-report.json"
        ),
        diagnostician: Diagnostician = diagnose_with_gemini,
        curriculum_architect: CurriculumArchitect | None = None,
        training_campaign: ScamTrainingCampaign | None = None,
    ) -> None:
        self._artifacts = artifact_store
        self._mission_path = mission_path
        self._original_curriculum_path = original_curriculum_path
        self._original_development_path = original_development_path
        self._baseline_predictions_path = baseline_predictions_path
        self._baseline_report_path = baseline_report_path
        self._diagnostician = diagnostician
        self._curriculum_architect = curriculum_architect or self._author_curriculum
        self._training_campaign = training_campaign

    @staticmethod
    def _journal_payload(artifact: StageArtifact) -> dict[str, Any]:
        projection = artifact.payload.get("journal_payload")
        if not isinstance(projection, dict):
            raise JournalError("scam stage artifact is missing its journal projection")
        if "artifact_uri" in projection or "artifact_sha256" in projection:
            raise JournalError("stored projection may not override artifact identity")
        return {
            "manifest_id": artifact.manifest_id,
            "artifact_uri": artifact.uri,
            "artifact_sha256": artifact.sha256,
            **projection,
        }

    def _existing(
        self, cycle_id: str, stage: Stage, manifest: MissionManifest
    ) -> dict[str, Any] | None:
        artifact = self._artifacts.read(cycle_id, stage, manifest.manifest_id)
        return self._journal_payload(artifact) if artifact else None

    def _create(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._journal_payload(
            self._artifacts.create(cycle_id, stage, manifest.manifest_id, payload)
        )

    def execute(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        entries: tuple[JournalEntry, ...],
    ) -> dict[str, Any]:
        if manifest.workflow not in {"scam_safety", "scam_safety_live"}:
            raise JournalError("scam executor received a different workflow")
        existing = self._existing(cycle_id, stage, manifest)
        if existing is not None:
            return existing
        if stage is Stage.DIAGNOSED:
            return self._diagnose(cycle_id, manifest)
        if stage is Stage.CURRICULUM_READY:
            return self._build_curriculum(cycle_id, manifest)
        if stage is Stage.TRAINED:
            return self._train(cycle_id, manifest)
        if stage is Stage.EVALUATED:
            return self._evaluate(cycle_id, manifest)
        if stage in {Stage.PROMOTED, Stage.REJECTED}:
            return self._finalize(cycle_id, stage, manifest, entries)
        raise JournalError(f"scam stage executor is not wired for {stage.value!r}")

    def _diagnose(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        mission = load_scam_mission(self._mission_path)
        if (
            mission.model_id != manifest.model_id
            or mission.model_revision != manifest.model_revision
        ):
            raise JournalError("scam mission checkpoint does not match the approved manifest")
        packet = build_scam_failure_packet(
            self._mission_path,
            self._original_development_path,
            self._baseline_predictions_path,
            self._baseline_report_path,
        )
        if packet.get("artifact_name") != manifest.trigger_artifact_name:
            raise JournalError("scam diagnosis does not match the approved trigger artifact")
        errors = packet.get("errors")
        if not isinstance(errors, list) or not errors:
            raise JournalError("approved scam mission no longer contains a repairable failure")
        allowed_ids = {str(row["case_id"]) for row in errors if isinstance(row, dict)}
        required_safety_ids = {
            str(row["case_id"])
            for row in errors
            if isinstance(row, dict)
            and row.get("suite") == "safety"
            and row.get("expected_label") == "block"
            and row.get("predicted_label") != "block"
        }
        try:
            plan = validate_scam_repair_plan(
                self._diagnostician(packet),
                allowed_evidence_ids=allowed_ids,
                required_safety_ids=required_safety_ids,
            )
        except (RuntimeError, ValueError) as exc:
            raise JournalError("Gemini diagnosis failed the bounded repair contract") from exc
        projection = {
            "actor": "gemini_adk_diagnostician",
            "model": TEACHER_MODEL_ID,
            "baseline_artifact": manifest.trigger_artifact_name,
            "observed_error_count": len(errors),
            "headline": plan["headline"],
            "evidence_case_ids": plan["evidence_case_ids"],
            "repair_families": plan["repair_families"],
            "authorized_action": "author bounded additive curriculum and train within manifest limits",
            "forbidden_action": "change labels, weaken the gate, inspect sealed evidence, or deploy",
        }
        return self._create(
            cycle_id,
            Stage.DIAGNOSED,
            manifest,
            {"journal_payload": projection, "failure_packet": packet, "repair_plan": plan},
        )

    def _author_curriculum(self, diagnosis_payload: dict[str, object]) -> dict[str, object]:
        plan = diagnosis_payload.get("repair_plan")
        packet = diagnosis_payload.get("failure_packet")
        if not isinstance(plan, dict) or not isinstance(packet, dict):
            raise JournalError("diagnosis artifact is missing private repair evidence")
        wrapper = {
            "schema_version": 1,
            "author_model": TEACHER_MODEL_ID,
            "mission_id": packet.get("mission_id"),
            "artifact_name": packet.get("artifact_name"),
            "source_hashes": packet.get("source_hashes"),
            "plan": plan,
        }
        with tempfile.TemporaryDirectory(prefix="nightwatch-scam-curriculum-") as temporary:
            root = Path(temporary)
            plan_path = root / "plan.json"
            target_path = root / "target.jsonl"
            development_path = root / "development.jsonl"
            repair_path = root / "repair.jsonl"
            combined_path = root / "combined.jsonl"
            evidence_path = root / "evidence.json"
            plan_path.write_text(json.dumps(wrapper, sort_keys=True), encoding="utf-8")
            asyncio.run(
                author_repair_bundle(
                    plan_path,
                    self._original_curriculum_path,
                    self._original_development_path,
                    target_path,
                    development_path,
                    repair_path,
                    combined_path,
                    evidence_path,
                )
            )
            return {
                "curriculum_jsonl": combined_path.read_text(encoding="utf-8"),
                "development_jsonl": development_path.read_text(encoding="utf-8"),
                "authoring_evidence": _json_file(evidence_path),
            }

    def _build_curriculum(
        self, cycle_id: str, manifest: MissionManifest
    ) -> dict[str, Any]:
        diagnosed = self._artifacts.read(cycle_id, Stage.DIAGNOSED, manifest.manifest_id)
        if diagnosed is None:
            raise JournalError("curriculum cannot start before immutable diagnosis evidence")
        try:
            bundle = self._curriculum_architect(diagnosed.payload)
            curriculum_jsonl = bundle["curriculum_jsonl"]
            development_jsonl = bundle["development_jsonl"]
            evidence = bundle["authoring_evidence"]
        except (KeyError, RuntimeError, ValueError, TypeError) as exc:
            raise JournalError("curriculum architect failed its bounded contract") from exc
        if not all(isinstance(value, str) and value.strip() for value in (curriculum_jsonl, development_jsonl)):
            raise JournalError("curriculum architect returned empty training evidence")
        if not isinstance(evidence, dict) or evidence.get("author_model") != TEACHER_MODEL_ID:
            raise JournalError("curriculum authoring evidence has the wrong teacher identity")
        with tempfile.TemporaryDirectory(prefix="nightwatch-scam-validate-") as temporary:
            root = Path(temporary)
            curriculum_path = root / "curriculum.jsonl"
            development_path = root / "development.jsonl"
            curriculum_path.write_text(curriculum_jsonl, encoding="utf-8")
            development_path.write_text(development_jsonl, encoding="utf-8")
            curriculum = load_scam_curriculum(curriculum_path)
            development = load_scam_eval_cases(development_path)
            assert_no_scam_eval_leakage(curriculum, development)
        curriculum_sha = hashlib.sha256(curriculum_jsonl.encode()).hexdigest()
        development_sha = hashlib.sha256(development_jsonl.encode()).hexdigest()
        if (
            evidence.get("combined_curriculum_sha256") != curriculum_sha
            or evidence.get("development_sha256") != development_sha
        ):
            raise JournalError("curriculum bytes do not match their authoring evidence")
        projection = {
            "architect": {"framework": "google_adk", "model": TEACHER_MODEL_ID},
            "repair_families": evidence.get("repair_families"),
            "curriculum_rows": evidence.get("combined_curriculum_rows"),
            "development_suite_counts": evidence.get("development_suite_counts"),
            "curriculum_sha256": curriculum_sha,
            "development_sha256": development_sha,
            "leakage_check": "passed",
        }
        return self._create(
            cycle_id,
            Stage.CURRICULUM_READY,
            manifest,
            {
                "journal_payload": projection,
                "curriculum_jsonl": curriculum_jsonl,
                "development_jsonl": development_jsonl,
                "authoring_evidence": evidence,
            },
        )

    def _train(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        if self._training_campaign is None:
            raise JournalError("scam training campaign is not configured")
        curriculum = self._artifacts.read(
            cycle_id, Stage.CURRICULUM_READY, manifest.manifest_id
        )
        if curriculum is None:
            raise JournalError("training cannot start before immutable curriculum evidence")
        result = self._training_campaign.run(cycle_id, manifest, curriculum)
        if not isinstance(result, dict):
            raise JournalError("scam training campaign returned a non-object result")
        attempts = result.get("attempts")
        candidate = result.get("candidate")
        if (
            not isinstance(attempts, list)
            or not 1 <= len(attempts) <= manifest.maximum_training_attempts
            or not isinstance(candidate, dict)
            or not isinstance(candidate.get("artifact_name"), str)
            or not isinstance(candidate.get("predictions_jsonl"), str)
        ):
            raise JournalError("scam training campaign exceeded or failed its manifest contract")
        projection = {
            "executor": "modal",
            "attempts": attempts,
            "selected_artifact": candidate["artifact_name"],
            "selection_policy": "bounded repair attempts; deterministic gate remains external",
            "maximum_training_attempts": manifest.maximum_training_attempts,
            "maximum_gpu_minutes": manifest.maximum_gpu_minutes,
        }
        return self._create(
            cycle_id,
            Stage.TRAINED,
            manifest,
            {"journal_payload": projection, "campaign_result": result},
        )

    def _evaluate(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        trained = self._artifacts.read(cycle_id, Stage.TRAINED, manifest.manifest_id)
        curriculum = self._artifacts.read(
            cycle_id, Stage.CURRICULUM_READY, manifest.manifest_id
        )
        if trained is None or curriculum is None:
            raise JournalError("evaluation requires immutable curriculum and training evidence")
        campaign = trained.payload.get("campaign_result")
        development_jsonl = curriculum.payload.get("development_jsonl")
        if not isinstance(campaign, dict) or not isinstance(development_jsonl, str):
            raise JournalError("training evidence is malformed")
        candidate = campaign.get("candidate")
        baseline_predictions = campaign.get("baseline_predictions_jsonl")
        if not isinstance(candidate, dict) or not isinstance(baseline_predictions, str):
            raise JournalError("training campaign is missing gate inputs")
        candidate_id = candidate.get("artifact_name")
        candidate_predictions = candidate.get("predictions_jsonl")
        if not isinstance(candidate_id, str) or not isinstance(candidate_predictions, str):
            raise JournalError("selected candidate is missing prediction evidence")
        with tempfile.TemporaryDirectory(prefix="nightwatch-scam-gate-") as temporary:
            root = Path(temporary)
            development_path = root / "development.jsonl"
            baseline_path = root / "baseline.jsonl"
            candidate_path = root / "candidate.jsonl"
            development_path.write_text(development_jsonl, encoding="utf-8")
            baseline_path.write_text(baseline_predictions, encoding="utf-8")
            candidate_path.write_text(candidate_predictions, encoding="utf-8")
            gate = build_scam_gate_record(
                self._mission_path,
                development_path,
                baseline_path,
                candidate_path,
                baseline_id=manifest.trigger_artifact_name,
                candidate_id=candidate_id,
            )
        decision = gate.get("decision")
        accepted = isinstance(decision, dict) and decision.get("decision") == "promote"
        if not isinstance(decision, dict):
            raise JournalError("deterministic scam gate returned malformed evidence")
        projection = {
            "accepted": accepted,
            "evaluator": "deterministic_scam_gate_v1",
            "baseline_artifact": manifest.trigger_artifact_name,
            "candidate_artifact": candidate_id,
            "decision": decision,
            "baseline": gate.get("baseline"),
            "candidate": gate.get("candidate"),
        }
        return self._create(
            cycle_id,
            Stage.EVALUATED,
            manifest,
            {"journal_payload": projection, "gate_record": gate},
        )

    def _finalize(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        entries: tuple[JournalEntry, ...],
    ) -> dict[str, Any]:
        if not entries or entries[-1].stage is not Stage.EVALUATED:
            raise JournalError("terminal scam decision requires an evaluated entry")
        accepted = entries[-1].payload.get("accepted")
        if not isinstance(accepted, bool) or accepted is not (stage is Stage.PROMOTED):
            raise JournalError("terminal scam stage conflicts with deterministic evaluation")
        evaluated = self._artifacts.read(cycle_id, Stage.EVALUATED, manifest.manifest_id)
        if evaluated is None:
            raise JournalError("terminal scam decision is missing immutable gate evidence")
        gate = evaluated.payload.get("gate_record")
        if not isinstance(gate, dict):
            raise JournalError("terminal scam gate evidence is malformed")
        projection = {
            "outcome": "qualified" if accepted else "refused",
            "artifact_name": gate.get("candidate_id"),
            "baseline_artifact": gate.get("baseline_id"),
            "model_id": manifest.model_id,
            "model_revision": manifest.model_revision,
            "qualified_under": "scam_gate_v1",
            "deployment_status": "qualified_not_deployed" if accepted else "refused_not_deployed",
            "scores": (
                gate.get("candidate", {}).get("scores")
                if isinstance(gate.get("candidate"), dict)
                else None
            ),
            "critical_misses": (
                gate.get("candidate", {}).get("critical_misses")
                if isinstance(gate.get("candidate"), dict)
                else None
            ),
            "decision": gate.get("decision"),
            "promotion_authority": "deterministic_code_only",
        }
        return self._create(
            cycle_id, stage, manifest, {"journal_payload": projection}
        )


class ManifestStageExecutor:
    """Route approved manifests without allowing callers to select executors."""

    def __init__(self, executors: dict[str, Any]) -> None:
        self._executors = dict(executors)

    def execute(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        entries: tuple[JournalEntry, ...],
    ) -> dict[str, Any]:
        try:
            executor = self._executors[manifest.workflow]
        except KeyError as exc:
            raise JournalError("approved mission workflow has no configured executor") from exc
        return executor.execute(cycle_id, stage, manifest, entries)
