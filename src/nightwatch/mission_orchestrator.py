from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Protocol

from nightwatch.contracts import Stage
from nightwatch.firestore_journal import validate_cycle_id
from nightwatch.journal import ALLOWED_TRANSITIONS, JournalEntry, JournalError
from nightwatch.model_config import GEMMA_MODEL_ID, GEMMA_MODEL_REVISION


@dataclass(frozen=True)
class MissionManifest:
    manifest_id: str
    subject: str
    trigger_artifact_name: str
    observed_safety_accuracy: float
    required_safety_accuracy: float
    model_id: str
    model_revision: str
    seed: int
    lora_rank: int
    epochs: float
    learning_rate: float
    maximum_training_attempts: int
    maximum_gpu_minutes: int
    workflow: str = "incident_triage"
    dataset_id: str | None = None
    dataset_sha256: str | None = None


SAFETY_270M_V1 = MissionManifest(
    manifest_id="safety-270m-v1",
    subject="small-model incident triage",
    trigger_artifact_name="classifier-1395040c-1e98fdcf-74d932a468",
    observed_safety_accuracy=25 / 30,
    required_safety_accuracy=0.9,
    model_id=GEMMA_MODEL_ID,
    model_revision=GEMMA_MODEL_REVISION,
    seed=20260809,
    lora_rank=8,
    epochs=3.0,
    learning_rate=1e-3,
    maximum_training_attempts=1,
    maximum_gpu_minutes=20,
)

SCAM_SAFETY_1B_V1 = MissionManifest(
    manifest_id="scam-safety-1b-v1",
    subject="scam message safety",
    trigger_artifact_name="scam-v0-de1e6009-2d77e636-c0e947096d",
    observed_safety_accuracy=30 / 36,
    required_safety_accuracy=0.95,
    model_id="google/gemma-3-1b-it",
    model_revision="dcc83ea841ab6100d6b47a070329e1ba4cf78752",
    seed=20260813,
    lora_rank=8,
    epochs=3.0,
    learning_rate=1e-3,
    maximum_training_attempts=8,
    maximum_gpu_minutes=20,
    workflow="scam_safety",
)

SCAM_SAFETY_LIVE_1B_V1 = MissionManifest(
    manifest_id="scam-safety-live-1b-v1",
    subject="scam message safety",
    trigger_artifact_name="scam-v0-de1e6009-2d77e636-c0e947096d",
    observed_safety_accuracy=30 / 36,
    required_safety_accuracy=0.95,
    model_id="google/gemma-3-1b-it",
    model_revision="dcc83ea841ab6100d6b47a070329e1ba4cf78752",
    seed=20260813,
    lora_rank=8,
    epochs=3.0,
    learning_rate=1e-3,
    maximum_training_attempts=1,
    maximum_gpu_minutes=20,
    workflow="scam_safety_live",
)

APPROVED_MANIFESTS = {
    SAFETY_270M_V1.manifest_id: SAFETY_270M_V1,
    SCAM_SAFETY_1B_V1.manifest_id: SCAM_SAFETY_1B_V1,
    SCAM_SAFETY_LIVE_1B_V1.manifest_id: SCAM_SAFETY_LIVE_1B_V1,
}

_DYNAMIC_MANIFEST = re.compile(r"^contract-[a-f0-9]{24}$")


class MissionJournal(Protocol):
    def read_cycle(self, cycle_id: str) -> list[JournalEntry]: ...

    def append_stage(
        self,
        cycle_id: str,
        stage: Stage,
        payload: dict[str, Any],
        *,
        timestamp: str | None = None,
    ) -> JournalEntry: ...


class MissionStageExecutor(Protocol):
    """Runs one stage and returns its immutable, journal-safe evidence payload.

    Implementations must key external effects by ``cycle_id`` and stage. A retry
    must load the already-created artifact rather than invoke Gemini or training
    again. The journal makes writes idempotent; the executor owns side-effect
    idempotency before the write.
    """

    def execute(
        self,
        cycle_id: str,
        stage: Stage,
        manifest: MissionManifest,
        entries: tuple[JournalEntry, ...],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MissionAdvance:
    cycle_id: str
    manifest_id: str
    stage: Stage
    terminal: bool
    entry_hash: str


def resolve_manifest(manifest_id: str) -> MissionManifest:
    try:
        return APPROVED_MANIFESTS[manifest_id]
    except (KeyError, TypeError) as exc:
        raise JournalError("mission manifest is not approved") from exc


def validate_manifest_id(manifest_id: str) -> None:
    if manifest_id in APPROVED_MANIFESTS:
        return
    if isinstance(manifest_id, str) and _DYNAMIC_MANIFEST.fullmatch(manifest_id):
        return
    raise JournalError("mission manifest identity is invalid")


def _created_payload(manifest: MissionManifest) -> dict[str, Any]:
    if manifest.workflow in {"scam_safety", "scam_safety_live"}:
        return {
            "mission_kind": "bounded_scam_safety_repair",
            "manifest_id": manifest.manifest_id,
            "subject": manifest.subject,
            "trigger": {
                "type": "scam_safety_gate_failure",
                "artifact_name": manifest.trigger_artifact_name,
                "target_accuracy": manifest.observed_safety_accuracy,
                "minimum_target_gain": 0.15,
                "minimum_safety_block_recall": manifest.required_safety_accuracy,
            },
            "candidate": {
                "model_id": manifest.model_id,
                "model_revision": manifest.model_revision,
                "seed": manifest.seed,
                "lora_rank": manifest.lora_rank,
                "epochs": manifest.epochs,
                "learning_rate": manifest.learning_rate,
            },
            "limits": {
                "maximum_training_attempts": manifest.maximum_training_attempts,
                "maximum_gpu_minutes": manifest.maximum_gpu_minutes,
            },
            "deployment_authorized": False,
        }
    return {
        "mission_kind": "bounded_model_qualification",
        "manifest_id": manifest.manifest_id,
        "subject": manifest.subject,
        "trigger": {
            "type": "qualification_failure",
            "artifact_name": manifest.trigger_artifact_name,
            "safety_accuracy": manifest.observed_safety_accuracy,
            "required_safety_accuracy": manifest.required_safety_accuracy,
        },
        "candidate": {
            "model_id": manifest.model_id,
            "model_revision": manifest.model_revision,
            "seed": manifest.seed,
            "lora_rank": manifest.lora_rank,
            "epochs": manifest.epochs,
            "learning_rate": manifest.learning_rate,
        },
        "limits": {
            "maximum_training_attempts": manifest.maximum_training_attempts,
            "maximum_gpu_minutes": manifest.maximum_gpu_minutes,
        },
        "deployment_authorized": False,
    }


def next_stage(entries: list[JournalEntry]) -> Stage | None:
    if not entries:
        return Stage.CREATED
    allowed = ALLOWED_TRANSITIONS[entries[-1].stage]
    if not allowed:
        return None
    if len(allowed) == 1:
        return next(iter(allowed))
    # The evaluated -> qualified/refused branch belongs to deterministic code in
    # the executor payload. Gemini never selects a terminal state.
    if entries[-1].stage is Stage.EVALUATED:
        accepted = entries[-1].payload.get("accepted")
        if not isinstance(accepted, bool):
            raise JournalError("evaluated evidence must contain a boolean accepted verdict")
        return Stage.PROMOTED if accepted else Stage.REJECTED
    raise JournalError("mission lifecycle has an unsupported branch")


def advance_mission(
    cycle_id: str,
    manifest_id: str,
    *,
    journal: MissionJournal,
    executor: MissionStageExecutor,
    expected_stage: Stage | None = None,
    manifest: MissionManifest | None = None,
) -> MissionAdvance:
    """Advance one durable stage; designed to be called by one Cloud Task.

    Exactly one stage is attempted per call. This keeps request duration bounded
    and lets Cloud Tasks retry a failed stage without replaying completed stages.
    """

    validate_cycle_id(cycle_id)
    if manifest is None:
        manifest = resolve_manifest(manifest_id)
    elif manifest.manifest_id != manifest_id:
        raise JournalError("resolved mission manifest has the wrong identity")
    validate_manifest_id(manifest.manifest_id)
    entries = journal.read_cycle(cycle_id)
    if entries:
        recorded_manifest = entries[0].payload.get("manifest_id")
        if recorded_manifest != manifest.manifest_id:
            raise JournalError("mission manifest does not match the existing cycle")

    if expected_stage is not None:
        completed = next((entry for entry in entries if entry.stage is expected_stage), None)
        if completed is not None:
            return MissionAdvance(
                cycle_id=cycle_id,
                manifest_id=manifest.manifest_id,
                stage=completed.stage,
                terminal=not bool(ALLOWED_TRANSITIONS[completed.stage]),
                entry_hash=completed.entry_hash,
            )

    stage = next_stage(entries)
    if stage is None:
        last = entries[-1]
        return MissionAdvance(
            cycle_id=cycle_id,
            manifest_id=manifest.manifest_id,
            stage=last.stage,
            terminal=True,
            entry_hash=last.entry_hash,
        )
    if expected_stage is not None and stage is not expected_stage:
        raise JournalError(
            f"mission task expected {expected_stage.value!r} but next stage is {stage.value!r}"
        )

    if stage is Stage.CREATED and manifest.workflow != "generic_text_classification":
        payload = _created_payload(manifest)
    else:
        payload = executor.execute(cycle_id, stage, manifest, tuple(entries))
        if not isinstance(payload, dict):
            raise JournalError("mission stage executor must return an evidence object")
        if payload.get("manifest_id") != manifest.manifest_id:
            raise JournalError("mission stage evidence has the wrong manifest identity")

    entry = journal.append_stage(cycle_id, stage, payload)
    return MissionAdvance(
        cycle_id=cycle_id,
        manifest_id=manifest.manifest_id,
        stage=entry.stage,
        terminal=not bool(ALLOWED_TRANSITIONS[entry.stage]),
        entry_hash=entry.entry_hash,
    )
