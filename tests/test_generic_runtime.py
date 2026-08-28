from __future__ import annotations

import hashlib

from nightwatch.generic_runtime import GCSRuntimeCallStore, GenericModalRuntime, RuntimeCall
from nightwatch.operator_contracts import build_mission_contract, parse_uploaded_dataset
from test_operator_contracts import contract_request, jsonl_bytes


class Calls:
    def __init__(self): self.call = None; self.claims = 0
    def read(self, cycle_id, contract_id, operation, input_sha256): return self.call
    def claim(self, cycle_id, contract_id, operation, input_sha256): self.claims += 1; return self.call is None
    def record(self, call): self.call = call; return call


class Backend:
    def __init__(self): self.spawns = 0; self.inputs = None
    def spawn(self, operation, contract_json, dataset_jsonl, curriculum_jsonl): self.spawns += 1; self.inputs = (operation, contract_json, dataset_jsonl, curriculum_jsonl); return "fc-baseline-001"
    def result(self, function_call_id, *, timeout_seconds):
        operation, contract_json, dataset_jsonl, curriculum_jsonl = self.inputs
        digest = hashlib.sha256("\n".join((operation, contract_json, dataset_jsonl, curriculum_jsonl or "")).encode()).hexdigest()
        import json
        return {"contract_id": json.loads(contract_json)["contract_id"], "operation": operation, "input_sha256": digest, "predictions": []}


def test_modal_runtime_reuses_the_recorded_call_instead_of_spending_twice() -> None:
    dataset = parse_uploaded_dataset(jsonl_bytes(), "jsonl")
    contract = build_mission_contract(contract_request(dataset.dataset_id), dataset)
    calls = Calls(); backend = Backend(); runtime = GenericModalRuntime(calls, backend)

    first = runtime.run("mission-runtime-001", "baseline", contract, dataset)
    second = runtime.run("mission-runtime-001", "baseline", contract, dataset)

    assert first == second
    assert backend.spawns == 1
    assert calls.claims == 1
    assert isinstance(calls.call, RuntimeCall)
    assert first["modal_call_id"] == "fc-baseline-001"


def test_runtime_call_ledger_uses_an_explicit_recovery_generation() -> None:
    assert GCSRuntimeCallStore._name("mission-runtime-001", "baseline", "call") == (
        "missions/mission-runtime-001/operations/modal-g3-baseline-call.json"
    )
