from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar

from nightwatch.contracts import Stage
from nightwatch.journal import ALLOWED_TRANSITIONS, GENESIS_HASH, JournalEntry, JournalError

MAX_PAYLOAD_BYTES = 256 * 1024
MAX_MISSION_ENTRIES = len(Stage)
FIRESTORE_TIMEOUT_SECONDS = 10.0
_CYCLE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
_T = TypeVar("_T")


class TransactionalDecorator(Protocol):
    def __call__(self, function: Callable[..., _T]) -> Callable[..., _T]: ...


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise JournalError("payload must be JSON serializable") from exc


def validate_cycle_id(cycle_id: str) -> None:
    if not _CYCLE_ID.fullmatch(cycle_id):
        raise JournalError(
            "cycle_id must contain 1-128 lowercase letters, digits, underscores, or hyphens"
        )


def _validate_input(cycle_id: str, payload: dict[str, Any]) -> None:
    validate_cycle_id(cycle_id)
    if not isinstance(payload, dict):
        raise JournalError("payload must be an object")
    if len(_canonical_json(payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise JournalError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")


def _entry_from_data(data: dict[str, Any]) -> JournalEntry:
    try:
        raw = {
            "cycle_id": data["cycle_id"],
            "stage": data["stage"],
            "timestamp": data["timestamp"],
            "payload": data["payload"],
            "previous_hash": data["previous_hash"],
        }
        supplied_hash = data["entry_hash"]
        actual_hash = hashlib.sha256(_canonical_json(raw).encode("utf-8")).hexdigest()
        if supplied_hash != actual_hash:
            raise JournalError("stored entry hash does not match its contents")
        return JournalEntry(
            cycle_id=str(raw["cycle_id"]),
            stage=Stage(raw["stage"]),
            timestamp=str(raw["timestamp"]),
            payload=dict(raw["payload"]),
            previous_hash=str(raw["previous_hash"]),
            entry_hash=str(supplied_hash),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, JournalError):
            raise
        raise JournalError("stored entry is malformed") from exc


class FirestoreJournal:
    """Transaction-safe mission journal backed by Firestore document primitives.

    The client is injected so the domain and retry behavior can be tested without
    creating a Firestore database. Production construction uses ``from_default``.
    """

    def __init__(
        self,
        client: Any,
        *,
        transactional: TransactionalDecorator,
        collection: str = "missions",
    ) -> None:
        self._client = client
        self._transactional = transactional
        self._collection = collection

    @classmethod
    def from_default(cls, *, project: str | None = None) -> FirestoreJournal:
        try:
            from google.cloud import firestore
        except ImportError as exc:
            raise RuntimeError("install the 'cloud' extra to use FirestoreJournal") from exc
        return cls(firestore.Client(project=project), transactional=firestore.transactional)

    def append_stage(
        self,
        cycle_id: str,
        stage: Stage,
        payload: dict[str, Any],
        *,
        timestamp: str | None = None,
    ) -> JournalEntry:
        _validate_input(cycle_id, payload)
        recorded_at = timestamp or datetime.now(timezone.utc).isoformat()
        mission_ref = self._client.collection(self._collection).document(cycle_id)
        entry_ref = mission_ref.collection("entries").document(stage.value)
        transaction = self._client.transaction(max_attempts=5)

        @self._transactional
        def append(transaction: Any) -> JournalEntry:
            entry_snapshot = entry_ref.get(
                transaction=transaction,
                timeout=FIRESTORE_TIMEOUT_SECONDS,
            )
            mission_snapshot = mission_ref.get(
                transaction=transaction,
                timeout=FIRESTORE_TIMEOUT_SECONDS,
            )
            if entry_snapshot.exists:
                existing = _entry_from_data(entry_snapshot.to_dict())
                if not mission_snapshot.exists:
                    raise JournalError("stored entry has no mission head")
                if existing.cycle_id != cycle_id or existing.stage is not stage:
                    raise JournalError("stored entry identity does not match its document path")
                if existing.payload == payload:
                    return existing
                raise JournalError(f"stage {stage.value!r} already exists with different payload")

            if mission_snapshot.exists:
                mission = mission_snapshot.to_dict()
                try:
                    current_stage = Stage(mission["current_stage"])
                    previous_hash = str(mission["head_hash"])
                    sequence = int(mission["entry_count"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise JournalError("mission head is malformed") from exc
                if stage not in ALLOWED_TRANSITIONS[current_stage]:
                    raise JournalError(
                        f"invalid transition {current_stage.value!r} -> {stage.value!r}"
                    )
            else:
                if stage is not Stage.CREATED:
                    raise JournalError("a cycle must start at created")
                previous_hash = GENESIS_HASH
                sequence = 0

            raw = {
                "cycle_id": cycle_id,
                "stage": stage.value,
                "timestamp": recorded_at,
                "payload": payload,
                "previous_hash": previous_hash,
            }
            entry_hash = hashlib.sha256(_canonical_json(raw).encode("utf-8")).hexdigest()
            entry_data = {**raw, "entry_hash": entry_hash, "sequence": sequence}
            mission_data = {
                "cycle_id": cycle_id,
                "current_stage": stage.value,
                "head_hash": entry_hash,
                "entry_count": sequence + 1,
                "terminal": not ALLOWED_TRANSITIONS[stage],
                "updated_at": recorded_at,
            }
            if sequence == 0:
                mission_data["created_at"] = recorded_at

            transaction.set(entry_ref, entry_data)
            transaction.set(mission_ref, mission_data, merge=sequence > 0)
            return _entry_from_data(entry_data)

        return append(transaction)

    def read_cycle(self, cycle_id: str) -> list[JournalEntry]:
        validate_cycle_id(cycle_id)
        mission_ref = self._client.collection(self._collection).document(cycle_id)
        mission_snapshot = mission_ref.get(timeout=FIRESTORE_TIMEOUT_SECONDS)
        if not mission_snapshot.exists:
            return []
        mission = mission_snapshot.to_dict()
        query = (
            mission_ref.collection("entries")
            .order_by("sequence")
            .limit(MAX_MISSION_ENTRIES + 1)
        )
        rows = [
            snapshot.to_dict()
            for snapshot in query.stream(timeout=FIRESTORE_TIMEOUT_SECONDS)
        ]
        if len(rows) > MAX_MISSION_ENTRIES:
            raise JournalError("mission contains more stages than the lifecycle allows")
        entries = [_entry_from_data(row) for row in rows]
        expected_previous = GENESIS_HASH
        for sequence, (row, entry) in enumerate(zip(rows, entries, strict=True)):
            if (
                row.get("sequence") != sequence
                or entry.cycle_id != cycle_id
                or entry.previous_hash != expected_previous
            ):
                raise JournalError("stored mission hash chain is broken")
            expected_previous = entry.entry_hash
        try:
            if (
                mission["entry_count"] != len(entries)
                or mission["head_hash"] != expected_previous
                or mission["current_stage"] != entries[-1].stage.value
            ):
                raise JournalError("mission head does not match its entries")
        except (KeyError, IndexError, TypeError) as exc:
            if isinstance(exc, JournalError):
                raise
            raise JournalError("mission head is malformed") from exc
        return entries
