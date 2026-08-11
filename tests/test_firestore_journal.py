from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from nightwatch.contracts import Stage
from nightwatch.firestore_journal import FirestoreJournal, JournalError, MAX_PAYLOAD_BYTES


@dataclass
class FakeSnapshot:
    data: dict[str, Any] | None

    @property
    def exists(self) -> bool:
        return self.data is not None

    def to_dict(self) -> dict[str, Any]:
        assert self.data is not None
        return dict(self.data)


class FakeDocument:
    def __init__(self, client: FakeClient, path: tuple[str, ...]) -> None:
        self.client = client
        self.path = path

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.client, (*self.path, name))

    def get(self, transaction: FakeTransaction | None = None) -> FakeSnapshot:
        return FakeSnapshot(self.client.documents.get(self.path))


class FakeQuery:
    def __init__(self, client: FakeClient, path: tuple[str, ...]) -> None:
        self.client = client
        self.path = path
        self.maximum = 100

    def order_by(self, field: str) -> FakeQuery:
        assert field == "sequence"
        return self

    def limit(self, maximum: int) -> FakeQuery:
        self.maximum = maximum
        return self

    def stream(self) -> list[FakeSnapshot]:
        rows = [
            data
            for path, data in self.client.documents.items()
            if path[:-1] == self.path
        ]
        return [FakeSnapshot(row) for row in sorted(rows, key=lambda row: row["sequence"])][
            : self.maximum
        ]


class FakeCollection(FakeQuery):
    def document(self, name: str) -> FakeDocument:
        return FakeDocument(self.client, (*self.path, name))


class FakeTransaction:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def set(self, reference: FakeDocument, data: dict[str, Any], merge: bool = False) -> None:
        current = self.client.documents.get(reference.path, {}) if merge else {}
        self.client.documents[reference.path] = {**current, **data}


class FakeClient:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, ...], dict[str, Any]] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, (name,))

    def transaction(self, max_attempts: int) -> FakeTransaction:
        assert max_attempts == 5
        return FakeTransaction(self)


def immediate_transaction(function: Any) -> Any:
    return function


@pytest.fixture
def journal() -> FirestoreJournal:
    return FirestoreJournal(FakeClient(), transactional=immediate_transaction)


def test_firestore_journal_records_ordered_hash_chain(journal: FirestoreJournal) -> None:
    stages = [Stage.CREATED, Stage.DIAGNOSED, Stage.CURRICULUM_READY]
    for index, stage in enumerate(stages):
        journal.append_stage(
            "mission-001",
            stage,
            {"source_sha256": str(index) * 64},
            timestamp=f"2026-08-10T00:0{index}:00Z",
        )

    entries = journal.read_cycle("mission-001")

    assert [entry.stage for entry in entries] == stages
    assert entries[0].previous_hash == "0" * 64
    assert entries[1].previous_hash == entries[0].entry_hash
    assert entries[2].previous_hash == entries[1].entry_hash


def test_firestore_journal_replay_is_single_effect(journal: FirestoreJournal) -> None:
    first = journal.append_stage(
        "mission-001",
        Stage.CREATED,
        {"baseline": "v1"},
        timestamp="2026-08-10T00:00:00Z",
    )
    replay = journal.append_stage(
        "mission-001",
        Stage.CREATED,
        {"baseline": "v1"},
        timestamp="a-retry-does-not-rewrite-evidence",
    )

    assert replay == first
    assert len(journal.read_cycle("mission-001")) == 1


def test_firestore_journal_rejects_conflicting_replay(journal: FirestoreJournal) -> None:
    journal.append_stage("mission-001", Stage.CREATED, {"baseline": "v1"})

    with pytest.raises(JournalError, match="different payload"):
        journal.append_stage("mission-001", Stage.CREATED, {"baseline": "attacker"})


def test_firestore_journal_rejects_skipped_stage(journal: FirestoreJournal) -> None:
    journal.append_stage("mission-001", Stage.CREATED, {})

    with pytest.raises(JournalError, match="invalid transition"):
        journal.append_stage("mission-001", Stage.TRAINED, {})


def test_firestore_journal_rejects_unsafe_id_and_oversized_payload(
    journal: FirestoreJournal,
) -> None:
    with pytest.raises(JournalError, match="cycle_id"):
        journal.append_stage("../other-mission", Stage.CREATED, {})
    with pytest.raises(JournalError, match="payload exceeds"):
        journal.append_stage(
            "mission-001",
            Stage.CREATED,
            {"content": "x" * MAX_PAYLOAD_BYTES},
        )


def test_firestore_journal_detects_stored_tampering(journal: FirestoreJournal) -> None:
    journal.append_stage("mission-001", Stage.CREATED, {"baseline": "v1"})
    client = journal._client
    client.documents[("missions", "mission-001", "entries", "created")]["payload"] = {
        "baseline": "tampered"
    }

    with pytest.raises(JournalError, match="stored entry hash"):
        journal.read_cycle("mission-001")


def test_firestore_journal_reconciles_mission_head(journal: FirestoreJournal) -> None:
    journal.append_stage("mission-001", Stage.CREATED, {"baseline": "v1"})
    client = journal._client
    client.documents[("missions", "mission-001")]["head_hash"] = "f" * 64

    with pytest.raises(JournalError, match="mission head does not match"):
        journal.read_cycle("mission-001")
