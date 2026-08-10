from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nightwatch.contracts import Stage

GENESIS_HASH = "0" * 64
ALLOWED_TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    Stage.CREATED: frozenset({Stage.DIAGNOSED}),
    Stage.DIAGNOSED: frozenset({Stage.CURRICULUM_READY}),
    Stage.CURRICULUM_READY: frozenset({Stage.TRAINED}),
    Stage.TRAINED: frozenset({Stage.EVALUATED}),
    Stage.EVALUATED: frozenset({Stage.PROMOTED, Stage.REJECTED}),
    Stage.PROMOTED: frozenset(),
    Stage.REJECTED: frozenset(),
}


class JournalError(ValueError):
    pass


@dataclass(frozen=True)
class JournalEntry:
    cycle_id: str
    stage: Stage
    timestamp: str
    payload: dict[str, Any]
    previous_hash: str
    entry_hash: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash_entry(entry_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(entry_without_hash).encode("utf-8")).hexdigest()


def read_journal(path: Path) -> list[JournalEntry]:
    if not path.exists():
        return []
    entries: list[JournalEntry] = []
    expected_previous = GENESIS_HASH
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            supplied_hash = raw.pop("entry_hash")
            actual_hash = _hash_entry(raw)
            if supplied_hash != actual_hash or raw["previous_hash"] != expected_previous:
                raise JournalError(f"{path}:{line_number}: broken journal hash chain")
            entry = JournalEntry(
                cycle_id=raw["cycle_id"],
                stage=Stage(raw["stage"]),
                timestamp=raw["timestamp"],
                payload=raw["payload"],
                previous_hash=raw["previous_hash"],
                entry_hash=supplied_hash,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, JournalError):
                raise
            raise JournalError(f"{path}:{line_number}: malformed journal entry") from exc
        entries.append(entry)
        expected_previous = supplied_hash
    return entries


def append_stage(
    path: Path,
    cycle_id: str,
    stage: Stage,
    payload: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> JournalEntry:
    if not cycle_id or len(cycle_id) > 128:
        raise JournalError("cycle_id must contain 1-128 characters")
    entries = read_journal(path)
    cycle_entries = [entry for entry in entries if entry.cycle_id == cycle_id]
    prior_same_stage = next((entry for entry in cycle_entries if entry.stage == stage), None)
    if prior_same_stage is not None:
        if prior_same_stage.payload == payload:
            return prior_same_stage
        raise JournalError(f"stage {stage.value!r} already exists with different payload")
    if cycle_entries:
        current = cycle_entries[-1].stage
        if stage not in ALLOWED_TRANSITIONS[current]:
            raise JournalError(f"invalid transition {current.value!r} -> {stage.value!r}")
    elif stage is not Stage.CREATED:
        raise JournalError("a cycle must start at created")

    previous_hash = entries[-1].entry_hash if entries else GENESIS_HASH
    raw = {
        "cycle_id": cycle_id,
        "stage": stage.value,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "previous_hash": previous_hash,
    }
    entry_hash = _hash_entry(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical_json({**raw, "entry_hash": entry_hash}) + "\n")
    return JournalEntry(
        cycle_id=cycle_id,
        stage=stage,
        timestamp=raw["timestamp"],
        payload=payload,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
    )
