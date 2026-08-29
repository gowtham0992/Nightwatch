from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from nightwatch.contracts import Stage
from nightwatch.journal import JournalEntry, JournalError


FOLLOWUP_SCHEMA_VERSION = 1
FOLLOWUP_STATUS = "awaiting_operator_approval"
FOLLOWUP_AUTHORITY = "authenticated_operator"

_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_CYCLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CONTRACT_ID = re.compile(r"^contract-[a-f0-9]{24}$")
_DRAFT_ID = re.compile(r"^followup-[a-f0-9]{24}$")
_APPROVAL_ID = re.compile(r"^approval-[a-f0-9]{24}$")
_DISPATCH_ID = re.compile(r"^dispatch-[a-f0-9]{24}$")
_TASK_ID = re.compile(r"^mission-[a-f0-9]{40}$")

_INVARIANT_CAPABILITIES: dict[str, str] = {
    "minimum_target_gain": "target_repair",
    "maximum_regression_drop": "regression_guard",
    "minimum_safety_accuracy": "safety_boundary",
    "require_zero_critical_misses": "safety_boundary",
}
_CAPABILITY_ORDER = ("target_repair", "safety_boundary", "regression_guard")
_CAPABILITY_ROWS = {
    "target_repair": 12,
    "safety_boundary": 16,
    "regression_guard": 12,
}


class FollowupError(ValueError):
    pass


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FollowupError("follow-up evidence must be JSON serializable") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise FollowupError(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class RepairEmphasis:
    capability: str
    reason: str
    proposed_rows: int


@dataclass(frozen=True)
class FollowupRequirements:
    fresh_evidence_required: bool
    new_budget_authorization_required: bool
    maximum_lineage_depth: int


@dataclass(frozen=True)
class FollowupDraft:
    draft_id: str
    draft_sha256: str
    schema_version: int
    parent_cycle_id: str
    parent_manifest_id: str
    parent_head_sha256: str
    parent_dataset_sha256: str
    parent_evaluation_sha256: str
    failed_invariants: tuple[str, ...]
    repair_emphasis: tuple[RepairEmphasis, ...]
    proposed_maximum_gpu_minutes: int
    proposed_training_attempts: int
    rationale: str
    requirements: FollowupRequirements
    status: str
    execution_authorized: bool
    deployment_authorized: bool

    def _material(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("draft_id")
        value.pop("draft_sha256")
        return value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_summary(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "draft_sha256": self.draft_sha256,
            "schema_version": self.schema_version,
            "parent_cycle_id": self.parent_cycle_id,
            "parent_manifest_id": self.parent_manifest_id,
            "parent_head_sha256": self.parent_head_sha256,
            "parent_evaluation_sha256": self.parent_evaluation_sha256,
            "failed_invariants": list(self.failed_invariants),
            "repair_emphasis": [asdict(item) for item in self.repair_emphasis],
            "proposed_compute": {
                "maximum_gpu_minutes": self.proposed_maximum_gpu_minutes,
                "maximum_training_attempts": self.proposed_training_attempts,
            },
            "rationale": self.rationale,
            "requirements": asdict(self.requirements),
            "status": self.status,
            "execution_authorized": self.execution_authorized,
            "deployment_authorized": self.deployment_authorized,
        }


@dataclass(frozen=True)
class FollowupApproval:
    approval_id: str
    approval_sha256: str
    draft_id: str
    parent_cycle_id: str
    parent_head_sha256: str
    child_contract_id: str
    child_cycle_id: str
    fresh_dataset_sha256: str
    maximum_gpu_minutes: int
    maximum_training_attempts: int
    authority: str
    idempotency_sha256: str
    deployment_authorized: bool

    def _material(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("approval_id")
        value.pop("approval_sha256")
        return value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_summary(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "approval_sha256": self.approval_sha256,
            "draft_id": self.draft_id,
            "parent_cycle_id": self.parent_cycle_id,
            "parent_head_sha256": self.parent_head_sha256,
            "child_contract_id": self.child_contract_id,
            "child_cycle_id": self.child_cycle_id,
            "maximum_gpu_minutes": self.maximum_gpu_minutes,
            "maximum_training_attempts": self.maximum_training_attempts,
            "authority": self.authority,
            "fresh_evidence_confirmed": True,
            "deployment_authorized": self.deployment_authorized,
        }


@dataclass(frozen=True)
class FollowupDispatch:
    dispatch_id: str
    dispatch_sha256: str
    draft_id: str
    approval_id: str
    child_contract_id: str
    child_cycle_id: str
    task_id: str
    status: str

    def _material(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("dispatch_id")
        value.pop("dispatch_sha256")
        return value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_summary(self) -> dict[str, Any]:
        return {
            "dispatch_id": self.dispatch_id,
            "dispatch_sha256": self.dispatch_sha256,
            "draft_id": self.draft_id,
            "approval_id": self.approval_id,
            "child_contract_id": self.child_contract_id,
            "child_cycle_id": self.child_cycle_id,
            "task_id": self.task_id,
            "status": self.status,
        }


def _terminal_refusal(entries: Iterable[JournalEntry]) -> tuple[list[JournalEntry], JournalEntry, JournalEntry]:
    ordered = list(entries)
    if not ordered or ordered[-1].stage is not Stage.REJECTED:
        raise FollowupError("a follow-up can be drafted only for a refused terminal mission")
    evaluated = next((entry for entry in ordered if entry.stage is Stage.EVALUATED), None)
    if evaluated is None or evaluated.payload.get("accepted") is not False:
        raise FollowupError("the refused mission is missing deterministic evaluation evidence")
    return ordered, evaluated, ordered[-1]


def _rationale(failed_invariants: tuple[str, ...]) -> str:
    return (
        f"The candidate failed {len(failed_invariants)} frozen release invariants. Nightwatch "
        "converted those failures into a bounded repair plan, but the previous evaluation is "
        "now treated as spent evidence. "
        "A different frozen dataset and a separately authorized compute budget are required."
    )


def build_followup_draft(
    cycle_id: str,
    entries: Iterable[JournalEntry],
    parent_contract: Any,
) -> FollowupDraft:
    if not isinstance(cycle_id, str) or _CYCLE_ID.fullmatch(cycle_id) is None:
        raise FollowupError("parent cycle ID is malformed")
    if getattr(parent_contract, "lineage", None) is not None:
        raise FollowupError("the governed follow-up lineage limit has been reached")
    ordered, evaluated, terminal = _terminal_refusal(entries)
    manifest_id = ordered[0].payload.get("manifest_id")
    if manifest_id != getattr(parent_contract, "contract_id", None):
        raise FollowupError("parent contract does not match the refused mission")
    decision = evaluated.payload.get("decision")
    failed = decision.get("failed_invariants") if isinstance(decision, dict) else None
    if (
        not isinstance(failed, list)
        or not failed
        or any(item not in _INVARIANT_CAPABILITIES for item in failed)
        or len(set(failed)) != len(failed)
    ):
        raise FollowupError("refused mission has unsupported release invariants")
    failed_invariants = tuple(failed)
    requested = {_INVARIANT_CAPABILITIES[item] for item in failed_invariants}
    emphasis = tuple(
        RepairEmphasis(
            capability=capability,
            reason={
                "target_repair": "Recover the missed target gain without weakening protected behavior.",
                "safety_boundary": "Restore safety decisions and eliminate critical misses.",
                "regression_guard": "Preserve routine behavior while the repair changes the boundary.",
            }[capability],
            proposed_rows=_CAPABILITY_ROWS[capability],
        )
        for capability in _CAPABILITY_ORDER
        if capability in requested
    )
    parent_head = _require_sha256(terminal.entry_hash, "parent head")
    parent_dataset = _require_sha256(
        getattr(parent_contract, "dataset_sha256", None), "parent dataset"
    )
    evaluation_sha = _require_sha256(
        evaluated.payload.get("artifact_sha256"), "parent evaluation artifact"
    )
    material = {
        "schema_version": FOLLOWUP_SCHEMA_VERSION,
        "parent_cycle_id": cycle_id,
        "parent_manifest_id": manifest_id,
        "parent_head_sha256": parent_head,
        "parent_dataset_sha256": parent_dataset,
        "parent_evaluation_sha256": evaluation_sha,
        "failed_invariants": failed_invariants,
        "repair_emphasis": [asdict(item) for item in emphasis],
        "proposed_maximum_gpu_minutes": min(
            20, int(parent_contract.compute.maximum_gpu_minutes)
        ),
        "proposed_training_attempts": 1,
        "rationale": _rationale(failed_invariants),
        "requirements": asdict(
            FollowupRequirements(
                fresh_evidence_required=True,
                new_budget_authorization_required=True,
                maximum_lineage_depth=1,
            )
        ),
        "status": FOLLOWUP_STATUS,
        "execution_authorized": False,
        "deployment_authorized": False,
    }
    digest = _digest(material)
    return FollowupDraft(
        draft_id=f"followup-{digest[:24]}",
        draft_sha256=digest,
        repair_emphasis=emphasis,
        requirements=FollowupRequirements(**material["requirements"]),
        **{key: value for key, value in material.items() if key not in {"repair_emphasis", "requirements"}},
    )


def followup_draft_from_dict(value: object) -> FollowupDraft:
    try:
        if not isinstance(value, dict):
            raise FollowupError("stored follow-up draft is malformed")
        draft = FollowupDraft(
            draft_id=value["draft_id"],
            draft_sha256=value["draft_sha256"],
            schema_version=value["schema_version"],
            parent_cycle_id=value["parent_cycle_id"],
            parent_manifest_id=value["parent_manifest_id"],
            parent_head_sha256=value["parent_head_sha256"],
            parent_dataset_sha256=value["parent_dataset_sha256"],
            parent_evaluation_sha256=value["parent_evaluation_sha256"],
            failed_invariants=tuple(value["failed_invariants"]),
            repair_emphasis=tuple(RepairEmphasis(**item) for item in value["repair_emphasis"]),
            proposed_maximum_gpu_minutes=value["proposed_maximum_gpu_minutes"],
            proposed_training_attempts=value["proposed_training_attempts"],
            rationale=value["rationale"],
            requirements=FollowupRequirements(**value["requirements"]),
            status=value["status"],
            execution_authorized=value["execution_authorized"],
            deployment_authorized=value["deployment_authorized"],
        )
    except (KeyError, TypeError) as exc:
        raise FollowupError("stored follow-up draft is malformed") from exc
    if _DRAFT_ID.fullmatch(draft.draft_id or "") is None:
        raise FollowupError("stored follow-up draft ID is malformed")
    if draft.schema_version != FOLLOWUP_SCHEMA_VERSION:
        raise FollowupError("stored follow-up schema is unsupported")
    if draft.status != FOLLOWUP_STATUS or draft.execution_authorized or draft.deployment_authorized:
        raise FollowupError("stored follow-up draft contains unauthorized state")
    if _digest(draft._material()) != draft.draft_sha256:
        raise FollowupError("stored follow-up draft digest does not match")
    if draft.draft_id != f"followup-{draft.draft_sha256[:24]}":
        raise FollowupError("stored follow-up draft identity does not match its digest")
    _require_sha256(draft.parent_head_sha256, "parent head")
    _require_sha256(draft.parent_dataset_sha256, "parent dataset")
    _require_sha256(draft.parent_evaluation_sha256, "parent evaluation artifact")
    return draft


def build_followup_approval(
    draft: FollowupDraft,
    *,
    child_contract_id: str,
    child_cycle_id: str,
    fresh_dataset_sha256: str,
    maximum_gpu_minutes: int,
    idempotency_key: str,
) -> FollowupApproval:
    if _CONTRACT_ID.fullmatch(child_contract_id or "") is None:
        raise FollowupError("child contract identity is malformed")
    if _CYCLE_ID.fullmatch(child_cycle_id or "") is None:
        raise FollowupError("child cycle identity is malformed")
    fresh_sha = _require_sha256(fresh_dataset_sha256, "fresh dataset")
    if fresh_sha == draft.parent_dataset_sha256:
        raise FollowupError("follow-up evidence must differ from the parent mission")
    if isinstance(maximum_gpu_minutes, bool) or not 1 <= maximum_gpu_minutes <= draft.proposed_maximum_gpu_minutes:
        raise FollowupError("approved GPU budget exceeds the follow-up proposal")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise FollowupError("approval idempotency key is required")
    material = {
        "draft_id": draft.draft_id,
        "parent_cycle_id": draft.parent_cycle_id,
        "parent_head_sha256": draft.parent_head_sha256,
        "child_contract_id": child_contract_id,
        "child_cycle_id": child_cycle_id,
        "fresh_dataset_sha256": fresh_sha,
        "maximum_gpu_minutes": maximum_gpu_minutes,
        "maximum_training_attempts": 1,
        "authority": FOLLOWUP_AUTHORITY,
        "idempotency_sha256": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
        "deployment_authorized": False,
    }
    digest = _digest(material)
    return FollowupApproval(
        approval_id=f"approval-{digest[:24]}",
        approval_sha256=digest,
        **material,
    )


def followup_approval_from_dict(value: object) -> FollowupApproval:
    try:
        if not isinstance(value, dict):
            raise FollowupError("stored follow-up approval is malformed")
        approval = FollowupApproval(**value)
    except (KeyError, TypeError) as exc:
        raise FollowupError("stored follow-up approval is malformed") from exc
    if _APPROVAL_ID.fullmatch(approval.approval_id or "") is None:
        raise FollowupError("stored follow-up approval ID is malformed")
    if approval.authority != FOLLOWUP_AUTHORITY or approval.deployment_authorized:
        raise FollowupError("stored follow-up approval contains unauthorized state")
    if (
        _DRAFT_ID.fullmatch(approval.draft_id or "") is None
        or _CONTRACT_ID.fullmatch(approval.child_contract_id or "") is None
        or _CYCLE_ID.fullmatch(approval.parent_cycle_id or "") is None
        or _CYCLE_ID.fullmatch(approval.child_cycle_id or "") is None
        or isinstance(approval.maximum_gpu_minutes, bool)
        or not isinstance(approval.maximum_gpu_minutes, int)
        or approval.maximum_gpu_minutes < 1
        or approval.maximum_training_attempts != 1
    ):
        raise FollowupError("stored follow-up approval fields are invalid")
    _require_sha256(approval.parent_head_sha256, "parent head")
    _require_sha256(approval.fresh_dataset_sha256, "fresh dataset")
    _require_sha256(approval.idempotency_sha256, "idempotency hash")
    if _digest(approval._material()) != approval.approval_sha256:
        raise FollowupError("stored follow-up approval digest does not match")
    if approval.approval_id != f"approval-{approval.approval_sha256[:24]}":
        raise FollowupError("stored follow-up approval identity does not match its digest")
    return approval


def build_followup_dispatch(
    approval: FollowupApproval,
    *,
    task_id: str,
) -> FollowupDispatch:
    if _TASK_ID.fullmatch(task_id or "") is None:
        raise FollowupError("follow-up task identity is malformed")
    material = {
        "draft_id": approval.draft_id,
        "approval_id": approval.approval_id,
        "child_contract_id": approval.child_contract_id,
        "child_cycle_id": approval.child_cycle_id,
        "task_id": task_id,
        "status": "queued",
    }
    digest = _digest(material)
    return FollowupDispatch(
        dispatch_id=f"dispatch-{digest[:24]}",
        dispatch_sha256=digest,
        **material,
    )


def followup_dispatch_from_dict(value: object) -> FollowupDispatch:
    try:
        if not isinstance(value, dict):
            raise FollowupError("stored follow-up dispatch is malformed")
        dispatch = FollowupDispatch(**value)
    except (KeyError, TypeError) as exc:
        raise FollowupError("stored follow-up dispatch is malformed") from exc
    if _DISPATCH_ID.fullmatch(dispatch.dispatch_id or "") is None:
        raise FollowupError("stored follow-up dispatch ID is malformed")
    if dispatch.status != "queued" or _TASK_ID.fullmatch(dispatch.task_id or "") is None:
        raise FollowupError("stored follow-up dispatch contains invalid state")
    if (
        _DRAFT_ID.fullmatch(dispatch.draft_id or "") is None
        or _APPROVAL_ID.fullmatch(dispatch.approval_id or "") is None
        or _CONTRACT_ID.fullmatch(dispatch.child_contract_id or "") is None
        or _CYCLE_ID.fullmatch(dispatch.child_cycle_id or "") is None
    ):
        raise FollowupError("stored follow-up dispatch fields are invalid")
    if _digest(dispatch._material()) != dispatch.dispatch_sha256:
        raise FollowupError("stored follow-up dispatch digest does not match")
    if dispatch.dispatch_id != f"dispatch-{dispatch.dispatch_sha256[:24]}":
        raise FollowupError("stored follow-up dispatch identity does not match its digest")
    return dispatch


def validate_public_followup_summary(
    value: object,
    *,
    expected_cycle_id: str,
    expected_manifest_id: str | None = None,
    expected_head_sha256: str | None = None,
    expected_evaluation_sha256: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"cycle_id", "followup"}:
        raise JournalError("public follow-up projection is malformed")
    if value.get("cycle_id") != expected_cycle_id or not isinstance(value.get("followup"), dict):
        raise JournalError("public follow-up projection has the wrong mission identity")
    summary = value["followup"]
    required = {
        "draft_id", "draft_sha256", "schema_version", "parent_cycle_id",
        "parent_manifest_id", "parent_head_sha256", "parent_evaluation_sha256",
        "failed_invariants", "repair_emphasis", "proposed_compute", "rationale",
        "requirements", "status", "execution_authorized", "deployment_authorized",
    }
    if set(summary) != required or summary.get("parent_cycle_id") != expected_cycle_id:
        raise JournalError("public follow-up projection fields are invalid")
    if summary.get("status") != FOLLOWUP_STATUS or summary.get("execution_authorized") is not False or summary.get("deployment_authorized") is not False:
        raise JournalError("public follow-up projection grants unauthorized authority")
    for field in ("draft_sha256", "parent_head_sha256", "parent_evaluation_sha256"):
        try:
            _require_sha256(summary.get(field), field)
        except FollowupError as exc:
            raise JournalError("public follow-up projection has invalid evidence identity") from exc
    if _DRAFT_ID.fullmatch(str(summary.get("draft_id"))) is None:
        raise JournalError("public follow-up projection has invalid draft identity")
    expected = {
        "parent_manifest_id": expected_manifest_id,
        "parent_head_sha256": expected_head_sha256,
        "parent_evaluation_sha256": expected_evaluation_sha256,
    }
    if any(wanted is not None and summary.get(field) != wanted for field, wanted in expected.items()):
        raise JournalError("public follow-up projection does not match the published mission evidence")
    return value


def load_public_followup_summary(
    path: Path,
    *,
    expected_cycle_id: str,
    expected_manifest_id: str | None = None,
    expected_head_sha256: str | None = None,
    expected_evaluation_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise JournalError("public follow-up projection is unavailable") from exc
    if not raw or len(raw) > 64 * 1024:
        raise JournalError("public follow-up projection has an invalid size")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise JournalError("public follow-up projection is malformed") from exc
    return validate_public_followup_summary(
        value,
        expected_cycle_id=expected_cycle_id,
        expected_manifest_id=expected_manifest_id,
        expected_head_sha256=expected_head_sha256,
        expected_evaluation_sha256=expected_evaluation_sha256,
    )
