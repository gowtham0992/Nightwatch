from __future__ import annotations

import hashlib
import json

from nightwatch.contracts import Stage
from nightwatch.generic_evaluation import evaluate_predictions, validate_predictions
from nightwatch.generic_mission_stages import GenericTextClassificationStageExecutor
from nightwatch.journal import append_stage, read_journal
from nightwatch.mission_orchestrator import advance_mission
from nightwatch.operator_contracts import InMemoryOperatorStore, build_mission_contract, mission_manifest_from_contract, parse_uploaded_dataset
from nightwatch.stage_artifacts import StageArtifact
from test_operator_contracts import adaptive_contract_request, contract_request, dataset_rows, jsonl_bytes


class Journal:
    def __init__(self, path): self.path = path
    def read_cycle(self, cycle_id): return [entry for entry in read_journal(self.path) if entry.cycle_id == cycle_id]
    def append_stage(self, cycle_id, stage, payload, *, timestamp=None): return append_stage(self.path, cycle_id, stage, payload, timestamp=timestamp)


class Artifacts:
    def __init__(self): self.values = {}
    def read(self, cycle_id, stage, manifest_id): return self.values.get((cycle_id, stage, manifest_id))
    def create(self, cycle_id, stage, manifest_id, payload):
        raw = json.dumps(payload, sort_keys=True).encode()
        artifact = StageArtifact(cycle_id, stage, manifest_id, payload, hashlib.sha256(raw).hexdigest(), f"memory://{cycle_id}/{stage.value}")
        existing = self.values.setdefault((cycle_id, stage, manifest_id), artifact)
        assert existing.payload == payload
        return existing
    def create_specialist(self, cycle_id, stage, manifest_id, specialist, payload):
        raw = json.dumps(payload, sort_keys=True).encode()
        artifact = StageArtifact(cycle_id, stage, manifest_id, payload, hashlib.sha256(raw).hexdigest(), f"memory://{cycle_id}/{stage.value}/specialists/{specialist}")
        existing = self.values.setdefault((cycle_id, stage, manifest_id, specialist), artifact)
        assert existing.payload == payload
        return existing


class Runtime:
    def __init__(self): self.calls = []
    def run(self, cycle_id, operation, contract, dataset, curriculum=None):
        self.calls.append(operation)
        rows = dataset_rows()
        if operation == "baseline":
            predictions = [{"id": row["case"], "label": "routine", "confidence": 0.6} for row in rows]
            artifact = contract.baseline_artifact
            training = None
        else:
            predictions = [{"id": row["case"], "label": row["expected"], "confidence": 0.9} for row in rows]
            artifact = "candidate-001"
            training = {"runtime_seconds": 12.0, "examples": len(curriculum), "attempt": 1}
        evaluation = evaluate_predictions(artifact, validate_predictions(predictions, contract, dataset), contract, dataset)
        return {"operation": operation, "contract_id": contract.contract_id, "artifact_name": artifact, "predictions": predictions, "evaluation": evaluation, "training": training, "modal_call_id": f"fc-{operation}-001"}


def test_dynamic_mission_discovers_failure_and_reaches_deterministic_gate(tmp_path, monkeypatch) -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(contract_request(dataset.dataset_id), dataset)
    store = InMemoryOperatorStore(); store.create_dataset(dataset); store.create_contract(contract)
    manifest = mission_manifest_from_contract(contract)
    artifacts = Artifacts(); runtime = Runtime()
    executor = GenericTextClassificationStageExecutor(artifacts, store, runtime)

    async def diagnosis(packet, _contract):
        return {"headline": "Observed bounded failures", "failure_pattern": "The baseline confuses multiple approved labels in target and safety evidence.", "evidence_case_ids": [packet["errors"][0]["case_id"]], "repair_objective": "Restore the observed boundary without damaging protected behavior.", "protected_behaviors": ["Preserve ordinary messages.", "Preserve safety blocking."]}

    async def curriculum(_diagnosis, _packet, _contract):
        rows = [{"text": f"Original authored example {index}", "label": contract.labels[index % len(contract.labels)], "specialist": "fleet"} for index in range(24)]
        batches = []
        for batch_index, specialist in enumerate(("target_repair", "safety_boundary", "regression_guard")):
            start = batch_index * 8
            batches.append({
                "specialist": specialist,
                "rationale": f"Bounded rationale for {specialist}",
                "examples": [{"text": row["text"], "label": row["label"]} for row in rows[start:start + 8]],
            })
        return {"specialists": ["target_repair", "safety_boundary", "regression_guard"], "batches": batches, "rows": rows}

    monkeypatch.setattr("nightwatch.generic_mission_stages.diagnose_failures", diagnosis)
    monkeypatch.setattr("nightwatch.generic_mission_stages.author_parallel_curriculum", curriculum)
    journal = Journal(tmp_path / "journal.jsonl")
    expected = [Stage.CREATED, Stage.DIAGNOSED, Stage.CURRICULUM_READY, Stage.TRAINED, Stage.EVALUATED, Stage.PROMOTED]
    for stage in expected:
        result = advance_mission("mission-dynamic-001", contract.contract_id, journal=journal, executor=executor, expected_stage=stage, manifest=manifest)
        assert result.stage is stage

    entries = journal.read_cycle("mission-dynamic-001")
    assert entries[0].payload["trigger"]["type"] == "discovered_baseline_failure"
    assert entries[-2].payload["decision"]["authority"] == "deterministic_code_only"
    assert entries[-1].payload["deployment_status"] == "qualified_not_deployed"
    outputs = entries[2].payload["specialist_outputs"]
    assert [output["specialist"] for output in outputs] == ["target_repair", "safety_boundary", "regression_guard"]
    assert [output["row_count"] for output in outputs] == [8, 8, 8]
    assert len({output["artifact_sha256"] for output in outputs}) == 3
    assert runtime.calls == ["baseline", "candidate"]


def test_adaptive_mission_seals_registry_plan_before_a2a_invocation(tmp_path, monkeypatch) -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(adaptive_contract_request(dataset.dataset_id), dataset)
    store = InMemoryOperatorStore(); store.create_dataset(dataset); store.create_contract(contract)
    manifest = mission_manifest_from_contract(contract)
    artifacts = Artifacts(); runtime = Runtime()
    executor = GenericTextClassificationStageExecutor(artifacts, store, runtime)
    calls = {"discover": 0, "invoke": 0}

    async def diagnosis(packet, _contract):
        return {"headline": "Observed bounded failures", "failure_pattern": "The baseline confuses multiple approved labels in target and safety evidence.", "evidence_case_ids": [packet["errors"][0]["case_id"]], "repair_objective": "Restore the observed boundary without damaging protected behavior.", "protected_behaviors": ["Preserve ordinary messages.", "Preserve safety blocking."], "required_capabilities": ["target_repair", "safety_boundary"]}

    async def discover(_diagnosis, _contract):
        calls["discover"] += 1
        return {"schema_version": "nightwatch.delegation-plan.v1", "taxonomy_version": "nightwatch.repair-capabilities.v1", "registry_location": "projects/test/locations/us-central1", "required_capabilities": ["target_repair", "safety_boundary", "regression_guard"], "selected_agents": [{"specialist": specialist, "agent_urn": f"urn:agent:{specialist}", "card_sha256": str(index) * 64, "endpoint_origin": f"https://{specialist}.example", "service_account": f"{specialist}@example.iam.gserviceaccount.com", "capabilities": [specialist], "registry_resource": f"agents/{specialist}"} for index, specialist in enumerate(("target_repair", "safety_boundary", "regression_guard"), start=1)]}

    async def invoke(**kwargs):
        calls["invoke"] += 1
        batches = []
        for batch_index, specialist in enumerate(("target_repair", "safety_boundary", "regression_guard")):
            examples = [{"text": f"Adaptive original {batch_index}-{index}", "label": contract.labels[index % len(contract.labels)]} for index in range(8)]
            batches.append({"specialist": specialist, "assignment": "bounded", "rationale": f"Bounded rationale for {specialist}", "examples": examples, "a2a_receipt": {"agent_card_sha256": str(batch_index + 1) * 64, "request_sha256": "a" * 64, "response_sha256": "b" * 64}})
        return {"batches": batches, "receipts": []}

    monkeypatch.setattr("nightwatch.generic_mission_stages.diagnose_failures", diagnosis)
    monkeypatch.setattr("nightwatch.generic_mission_stages.discover_delegation_plan", discover)
    monkeypatch.setattr("nightwatch.generic_mission_stages.invoke_delegation_plan", invoke)
    journal = Journal(tmp_path / "adaptive.jsonl")
    for stage in (Stage.CREATED, Stage.DIAGNOSED, Stage.CURRICULUM_READY):
        advance_mission("mission-adaptive-001", contract.contract_id, journal=journal, executor=executor, expected_stage=stage, manifest=manifest)
    # A retry of an already sealed stage reads immutable evidence and cannot rediscover.
    executor.execute("mission-adaptive-001", Stage.DIAGNOSED, manifest, tuple(journal.read_cycle("mission-adaptive-001")))

    assert calls == {"discover": 1, "invoke": 1}
    diagnosed = artifacts.read("mission-adaptive-001", Stage.DIAGNOSED, contract.contract_id)
    assert len(diagnosed.payload["delegation_plan"]["selected_agents"]) == 3
    authored = artifacts.read("mission-adaptive-001", Stage.CURRICULUM_READY, contract.contract_id)
    assert all("a2a_receipt" in output for output in authored.payload["specialist_artifacts"])
