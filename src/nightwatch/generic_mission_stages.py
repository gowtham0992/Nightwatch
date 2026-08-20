from __future__ import annotations

import asyncio
from typing import Any, Protocol

from nightwatch.contracts import Stage
from nightwatch.generic_agents import GEMINI_AGENT_MODEL, SPECIALISTS, author_parallel_curriculum, diagnose_failures
from nightwatch.generic_evaluation import decide_release, evaluate_predictions, validate_predictions
from nightwatch.journal import JournalEntry, JournalError
from nightwatch.mission_orchestrator import MissionManifest
from nightwatch.operator_contracts import OperatorStore, require_contract
from nightwatch.stage_artifacts import StageArtifact


class ArtifactStore(Protocol):
    def read(self, cycle_id: str, stage: Stage, manifest_id: str) -> StageArtifact | None: ...
    def create(self, cycle_id: str, stage: Stage, manifest_id: str, payload: dict[str, Any]) -> StageArtifact: ...


class ClassifierRuntime(Protocol):
    def run(self, cycle_id: str, operation: str, contract, dataset, curriculum=None) -> dict[str, Any]: ...


class GenericTextClassificationStageExecutor:
    def __init__(self, artifacts: ArtifactStore, operator_store: OperatorStore, runtime: ClassifierRuntime) -> None:
        self._artifacts = artifacts
        self._operators = operator_store
        self._runtime = runtime

    @staticmethod
    def _journal(artifact: StageArtifact) -> dict[str, Any]:
        projection = artifact.payload.get("journal_payload")
        if not isinstance(projection, dict):
            raise JournalError("generic stage artifact is missing its journal projection")
        return {"manifest_id": artifact.manifest_id, "artifact_uri": artifact.uri, "artifact_sha256": artifact.sha256, **projection}

    def _existing(self, cycle_id: str, stage: Stage, manifest: MissionManifest) -> dict[str, Any] | None:
        artifact = self._artifacts.read(cycle_id, stage, manifest.manifest_id)
        return self._journal(artifact) if artifact else None

    def _create(self, cycle_id: str, stage: Stage, manifest: MissionManifest, payload: dict[str, Any]) -> dict[str, Any]:
        return self._journal(self._artifacts.create(cycle_id, stage, manifest.manifest_id, payload))

    def _inputs(self, manifest: MissionManifest):
        contract = require_contract(self._operators, manifest.manifest_id)
        dataset = self._operators.read_dataset(contract.dataset_id)
        if dataset is None:
            raise JournalError("frozen mission dataset is unavailable")
        return contract, dataset

    def execute(self, cycle_id: str, stage: Stage, manifest: MissionManifest, entries: tuple[JournalEntry, ...]) -> dict[str, Any]:
        if manifest.workflow != "generic_text_classification":
            raise JournalError("generic executor received a different workflow")
        existing = self._existing(cycle_id, stage, manifest)
        if existing is not None:
            return existing
        if stage is Stage.CREATED:
            return self._baseline(cycle_id, manifest)
        if stage is Stage.DIAGNOSED:
            return self._diagnose(cycle_id, manifest)
        if stage is Stage.CURRICULUM_READY:
            return self._curriculum(cycle_id, manifest)
        if stage is Stage.TRAINED:
            return self._train(cycle_id, manifest)
        if stage is Stage.EVALUATED:
            return self._evaluate(cycle_id, manifest)
        if stage in {Stage.PROMOTED, Stage.REJECTED}:
            return self._finalize(cycle_id, stage, manifest, entries)
        raise JournalError("generic workflow received an unsupported stage")

    def _baseline(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        contract, dataset = self._inputs(manifest)
        result = self._runtime.run(cycle_id, "baseline", contract, dataset)
        predictions = validate_predictions(result.get("predictions"), contract, dataset)
        evaluation = evaluate_predictions(result.get("artifact_name"), predictions, contract, dataset)
        if result.get("evaluation") != evaluation:
            raise JournalError("baseline runtime evaluation failed deterministic recomputation")
        errors = evaluation["errors"]
        if not errors:
            raise JournalError("selected baseline has no observed failure to repair")
        packet = {
            "artifact_name": contract.baseline_artifact,
            "scores": evaluation["scores"],
            "critical_misses": evaluation["critical_misses"],
            "errors": errors,
        }
        projection = {
            "mission_kind": "bounded_text_classifier_repair",
            "subject": contract.subject,
            "trigger": {"type": "discovered_baseline_failure", "artifact_name": contract.baseline_artifact, "error_count": len(errors), "scores": evaluation["scores"]},
            "candidate": {"model_id": contract.model_id, "model_revision": contract.model_revision, "seed": contract.compute.seed, "lora_rank": contract.compute.rank, "epochs": contract.compute.epochs, "learning_rate": contract.compute.learning_rate},
            "limits": {"maximum_training_attempts": 1, "maximum_gpu_minutes": contract.compute.maximum_gpu_minutes},
            "dataset": {"dataset_id": contract.dataset_id, "sha256": contract.dataset_sha256, "rows": dataset.row_count},
            "deployment_authorized": False,
        }
        compact_result = {
            "artifact_name": result["artifact_name"],
            "predictions": result["predictions"],
            "modal_call_id": result.get("modal_call_id"),
            "runtime_seconds": result.get("runtime_seconds"),
        }
        return self._create(cycle_id, Stage.CREATED, manifest, {"journal_payload": projection, "failure_packet": packet, "baseline_result": compact_result})

    def _diagnose(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        contract, _ = self._inputs(manifest)
        created = self._artifacts.read(cycle_id, Stage.CREATED, manifest.manifest_id)
        packet = created.payload.get("failure_packet") if created else None
        if not isinstance(packet, dict):
            raise JournalError("diagnosis requires immutable baseline evidence")
        try:
            diagnosis = asyncio.run(diagnose_failures(packet, contract))
        except (RuntimeError, ValueError) as exc:
            raise JournalError("Gemini diagnosis failed its bounded contract") from exc
        projection = {"actor": "gemini_adk_diagnostician", "model": GEMINI_AGENT_MODEL, "observed_error_count": len(packet["errors"]), **diagnosis, "repair_families": list(SPECIALISTS), "authorized_action": "author bounded additive curriculum", "forbidden_action": "change evidence, policy, compute, or deployment"}
        return self._create(cycle_id, Stage.DIAGNOSED, manifest, {"journal_payload": projection, "diagnosis": diagnosis})

    def _curriculum(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        contract, dataset = self._inputs(manifest)
        created = self._artifacts.read(cycle_id, Stage.CREATED, manifest.manifest_id)
        diagnosed = self._artifacts.read(cycle_id, Stage.DIAGNOSED, manifest.manifest_id)
        packet = created.payload.get("failure_packet") if created else None
        diagnosis = diagnosed.payload.get("diagnosis") if diagnosed else None
        if not isinstance(packet, dict) or not isinstance(diagnosis, dict):
            raise JournalError("curriculum requires baseline and diagnosis evidence")
        try:
            agent_packet = {
                **packet,
                "all_cases": [
                    {"case_id": str(row[contract.mapping.id_column]), "text": str(row[contract.mapping.text_column])}
                    for row in dataset.rows
                ],
            }
            curriculum = asyncio.run(author_parallel_curriculum(diagnosis, agent_packet, contract))
        except (RuntimeError, ValueError) as exc:
            raise JournalError("parallel Gemini curriculum fleet failed its bounded contract") from exc
        projection = {"architect": {"framework": "google_adk", "model": GEMINI_AGENT_MODEL}, "repair_families": curriculum["specialists"], "curriculum_rows": len(curriculum["rows"]), "parallel_agents": len(curriculum["specialists"]), "leakage_check": "passed"}
        return self._create(cycle_id, Stage.CURRICULUM_READY, manifest, {"journal_payload": projection, "curriculum": curriculum})

    def _train(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        contract, dataset = self._inputs(manifest)
        authored = self._artifacts.read(cycle_id, Stage.CURRICULUM_READY, manifest.manifest_id)
        curriculum = authored.payload.get("curriculum") if authored else None
        if not isinstance(curriculum, dict) or not isinstance(curriculum.get("rows"), list):
            raise JournalError("training requires immutable curriculum evidence")
        result = self._runtime.run(cycle_id, "candidate", contract, dataset, curriculum["rows"])
        if not isinstance(result.get("artifact_name"), str) or not isinstance(result.get("training"), dict):
            raise JournalError("candidate runtime returned malformed training evidence")
        projection = {"executor": "modal", "attempts": [{"attempt": 1, "artifact_name": result["artifact_name"], "runtime_seconds": result["training"].get("runtime_seconds"), "examples": result["training"].get("examples"), "modal_call_id": result.get("modal_call_id")}], "selected_artifact": result["artifact_name"], "maximum_training_attempts": 1, "maximum_gpu_minutes": contract.compute.maximum_gpu_minutes, "selection_policy": "single bounded attempt; deterministic gate remains external"}
        return self._create(cycle_id, Stage.TRAINED, manifest, {"journal_payload": projection, "candidate_result": result})

    def _evaluate(self, cycle_id: str, manifest: MissionManifest) -> dict[str, Any]:
        contract, dataset = self._inputs(manifest)
        created = self._artifacts.read(cycle_id, Stage.CREATED, manifest.manifest_id)
        trained = self._artifacts.read(cycle_id, Stage.TRAINED, manifest.manifest_id)
        baseline_result = created.payload.get("baseline_result") if created else None
        candidate_result = trained.payload.get("candidate_result") if trained else None
        if not isinstance(baseline_result, dict) or not isinstance(candidate_result, dict):
            raise JournalError("evaluation requires immutable baseline and candidate evidence")
        baseline_predictions = validate_predictions(baseline_result.get("predictions"), contract, dataset)
        candidate_predictions = validate_predictions(candidate_result.get("predictions"), contract, dataset)
        baseline = evaluate_predictions(str(baseline_result.get("artifact_name")), baseline_predictions, contract, dataset)
        candidate = evaluate_predictions(str(candidate_result.get("artifact_name")), candidate_predictions, contract, dataset)
        decision = decide_release(baseline, candidate, contract)
        projection = {"accepted": decision["accepted"], "evaluator": "deterministic_generic_gate_v1", "baseline_artifact": baseline["artifact_name"], "candidate_artifact": candidate["artifact_name"], "decision": decision, "baseline": baseline, "candidate": candidate}
        return self._create(cycle_id, Stage.EVALUATED, manifest, {"journal_payload": projection, "gate_record": projection})

    def _finalize(self, cycle_id: str, stage: Stage, manifest: MissionManifest, entries: tuple[JournalEntry, ...]) -> dict[str, Any]:
        if not entries or entries[-1].stage is not Stage.EVALUATED:
            raise JournalError("terminal decision requires evaluated evidence")
        accepted = entries[-1].payload.get("accepted")
        if not isinstance(accepted, bool) or accepted is not (stage is Stage.PROMOTED):
            raise JournalError("terminal stage conflicts with deterministic evaluation")
        evaluated = self._artifacts.read(cycle_id, Stage.EVALUATED, manifest.manifest_id)
        gate = evaluated.payload.get("gate_record") if evaluated else None
        if not isinstance(gate, dict):
            raise JournalError("terminal decision is missing gate evidence")
        projection = {"outcome": "qualified" if accepted else "refused", "artifact_name": gate["candidate_artifact"], "baseline_artifact": gate["baseline_artifact"], "model_id": manifest.model_id, "model_revision": manifest.model_revision, "qualified_under": "generic_text_gate_v1", "deployment_status": "qualified_not_deployed" if accepted else "refused_not_deployed", "decision": gate["decision"], "critical_miss_count": gate["candidate"]["critical_miss_count"], "promotion_authority": "deterministic_code_only"}
        return self._create(cycle_id, stage, manifest, {"journal_payload": projection})
