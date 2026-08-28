from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from google.api_core.exceptions import Conflict, NotFound, PreconditionFailed

from nightwatch.firestore_journal import validate_cycle_id
from nightwatch.journal import JournalError
from nightwatch.mission_orchestrator import validate_manifest_id
from nightwatch.operator_contracts import FrozenDataset, MissionContract
from nightwatch.stage_artifacts import GCS_TIMEOUT_SECONDS

_CALL_ID = re.compile(r"^fc-[A-Za-z0-9_-]{4,200}$")
_OPERATION = re.compile(r"^(baseline|candidate)$")
_RUNTIME_GENERATION = "g3"


@dataclass(frozen=True)
class RuntimeCall:
    cycle_id: str
    contract_id: str
    operation: str
    input_sha256: str
    function_call_id: str


class RuntimeCallStore(Protocol):
    def read(self, cycle_id: str, contract_id: str, operation: str, input_sha256: str) -> RuntimeCall | None: ...
    def claim(self, cycle_id: str, contract_id: str, operation: str, input_sha256: str) -> bool: ...
    def record(self, call: RuntimeCall) -> RuntimeCall: ...


class GenericModalBackend(Protocol):
    def spawn(
        self,
        operation: str,
        contract_json: str,
        dataset_jsonl: str,
        curriculum_jsonl: str | None,
    ) -> str: ...
    def result(self, function_call_id: str, *, timeout_seconds: float) -> dict[str, Any]: ...


def _validate(cycle_id: str, contract_id: str, operation: str, digest: str) -> None:
    validate_cycle_id(cycle_id)
    validate_manifest_id(contract_id)
    if not _OPERATION.fullmatch(operation) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise JournalError("generic runtime operation identity is invalid")


class GCSRuntimeCallStore:
    def __init__(self, bucket: Any) -> None:
        self._bucket = bucket

    @classmethod
    def from_default(cls, *, project: str | None, bucket_name: str) -> GCSRuntimeCallStore:
        from google.cloud import storage
        return cls(storage.Client(project=project).bucket(bucket_name))

    @staticmethod
    def _name(cycle_id: str, operation: str, suffix: str) -> str:
        # A generation is advanced only when a deployed runtime failed before
        # producing a usable result. Old create-only records stay immutable and
        # auditable; the repaired runtime receives its own one-call allowance.
        return f"missions/{cycle_id}/operations/modal-{_RUNTIME_GENERATION}-{operation}-{suffix}.json"

    def read(self, cycle_id: str, contract_id: str, operation: str, input_sha256: str) -> RuntimeCall | None:
        _validate(cycle_id, contract_id, operation, input_sha256)
        try:
            raw = self._bucket.blob(self._name(cycle_id, operation, "call")).download_as_bytes(timeout=GCS_TIMEOUT_SECONDS)
        except NotFound:
            return None
        try:
            value = json.loads(raw)
            call = RuntimeCall(**value)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
            raise JournalError("generic runtime call record is malformed") from exc
        _validate(call.cycle_id, call.contract_id, call.operation, call.input_sha256)
        if call != RuntimeCall(cycle_id, contract_id, operation, input_sha256, call.function_call_id) or not _CALL_ID.fullmatch(call.function_call_id):
            raise JournalError("generic runtime call record has the wrong identity")
        return call

    def claim(self, cycle_id: str, contract_id: str, operation: str, input_sha256: str) -> bool:
        _validate(cycle_id, contract_id, operation, input_sha256)
        raw = json.dumps({"contract_id": contract_id, "input_sha256": input_sha256, "operation": operation}, sort_keys=True, separators=(",", ":"))
        try:
            self._bucket.blob(self._name(cycle_id, operation, "claim")).upload_from_string(raw, content_type="application/json", if_generation_match=0, timeout=GCS_TIMEOUT_SECONDS)
        except (Conflict, PreconditionFailed):
            return False
        return True

    def record(self, call: RuntimeCall) -> RuntimeCall:
        _validate(call.cycle_id, call.contract_id, call.operation, call.input_sha256)
        if not _CALL_ID.fullmatch(call.function_call_id):
            raise JournalError("Modal call ID is malformed")
        raw = json.dumps(call.__dict__, sort_keys=True, separators=(",", ":"))
        blob = self._bucket.blob(self._name(call.cycle_id, call.operation, "call"))
        try:
            blob.upload_from_string(raw, content_type="application/json", if_generation_match=0, timeout=GCS_TIMEOUT_SECONDS)
        except (Conflict, PreconditionFailed):
            existing = self.read(call.cycle_id, call.contract_id, call.operation, call.input_sha256)
            if existing != call:
                raise JournalError("Modal call record already exists with different identity")
            return existing
        return call


class ModalGenericBackend:
    def spawn(self, operation: str, contract_json: str, dataset_jsonl: str, curriculum_jsonl: str | None) -> str:
        import modal
        function = modal.Function.from_name("nightwatch-generic", "run_generic_classifier")
        return function.spawn(operation, contract_json, dataset_jsonl, curriculum_jsonl).object_id

    def result(self, function_call_id: str, *, timeout_seconds: float) -> dict[str, Any]:
        import modal
        result = modal.FunctionCall.from_id(function_call_id).get(timeout=timeout_seconds)
        if not isinstance(result, dict):
            raise JournalError("Modal generic classifier returned a non-object result")
        return result


class GenericModalRuntime:
    def __init__(self, calls: RuntimeCallStore, backend: GenericModalBackend | None = None) -> None:
        self._calls = calls
        self._backend = backend or ModalGenericBackend()

    def run(
        self,
        cycle_id: str,
        operation: str,
        contract: MissionContract,
        dataset: FrozenDataset,
        curriculum: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        contract_json = json.dumps(contract.to_dict(), sort_keys=True, separators=(",", ":"))
        dataset_jsonl = dataset.canonical_bytes().decode()
        curriculum_jsonl = (
            "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in curriculum)
            if curriculum is not None else None
        )
        material = "\n".join((operation, contract_json, dataset_jsonl, curriculum_jsonl or "")).encode()
        digest = hashlib.sha256(material).hexdigest()
        call = self._calls.read(cycle_id, contract.contract_id, operation, digest)
        if call is None:
            if not self._calls.claim(cycle_id, contract.contract_id, operation, digest):
                call = self._calls.read(cycle_id, contract.contract_id, operation, digest)
                if call is None:
                    raise JournalError("Modal operation is claimed without a call record; refusing duplicate spend")
            else:
                call = self._calls.record(RuntimeCall(
                    cycle_id, contract.contract_id, operation, digest,
                    self._backend.spawn(operation, contract_json, dataset_jsonl, curriculum_jsonl),
                ))
        result = self._backend.result(call.function_call_id, timeout_seconds=contract.compute.maximum_gpu_minutes * 60)
        if result.get("contract_id") != contract.contract_id or result.get("operation") != operation or result.get("input_sha256") != digest:
            raise JournalError("Modal result is not bound to the frozen operation inputs")
        return {**result, "modal_call_id": call.function_call_id}
