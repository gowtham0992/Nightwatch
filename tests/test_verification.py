from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from nightwatch.contracts import Stage
from nightwatch.journal import GENESIS_HASH, JournalEntry, JournalError
from nightwatch.verification import GCSMissionVerificationStore, GCSVerificationReceiptReader


class StubJournal:
    def __init__(self, entry: JournalEntry | None) -> None:
        self.entry = entry

    def read_cycle(self, cycle_id: str) -> list[JournalEntry]:
        return [self.entry] if self.entry else []


class FakeBlob:
    def __init__(self, name: str, *, exists: bool, payload: bytes | None = None) -> None:
        self.name = name
        self.exists = exists
        self.payload = payload
        self.uploads: list[tuple[bytes, dict[str, object]]] = []
        self.time_created = datetime(2026, 8, 12, 20, 30, 3, tzinfo=timezone.utc) if exists else None

    def reload(self, **kwargs: object) -> None:
        assert kwargs == {"timeout": 10.0}
        if not self.exists:
            raise NotFound("missing")

    def upload_from_string(self, payload: bytes, **kwargs: object) -> None:
        self.uploads.append((payload, kwargs))
        if self.exists:
            raise PreconditionFailed("generation-zero precondition failed")
        self.exists = True

    def download_as_bytes(self, **kwargs: object) -> bytes:
        assert kwargs == {"timeout": 10.0}
        if not self.exists:
            raise NotFound("missing")
        assert self.payload is not None
        return self.payload


class FakeBucket:
    def __init__(self, *, exists: bool = False, payload: bytes | None = None) -> None:
        self.exists = exists
        self.payload = payload
        self.blobs: list[FakeBlob] = []

    def blob(self, name: str) -> FakeBlob:
        blob = FakeBlob(name, exists=self.exists, payload=self.payload)
        self.blobs.append(blob)
        return blob


def retained_entry() -> JournalEntry:
    return JournalEntry(
        cycle_id="mission-001",
        stage=Stage.PROMOTED,
        timestamp="2026-08-11T00:00:00Z",
        payload={},
        previous_hash=GENESIS_HASH,
        entry_hash="b" * 64,
    )


def test_verification_creates_content_derived_receipt_with_generation_precondition() -> None:
    bucket = FakeBucket()
    store = GCSMissionVerificationStore(bucket, journal=StubJournal(retained_entry()))
    receipt_id = "verify-" + "a" * 40

    receipt = store.verify("mission-001", "b" * 64, receipt_id)

    blob = bucket.blobs[0]
    assert blob.name == f"verifications/mission-001/{receipt_id}.json"
    payload, options = blob.uploads[0]
    assert json.loads(payload) == {
        "cycle_id": "mission-001",
        "entry_count": 1,
        "head_hash": "b" * 64,
        "verification_id": receipt_id,
    }
    assert options == {
        "content_type": "application/json",
        "if_generation_match": 0,
        "timeout": 10.0,
    }
    assert receipt.entry_count == 1


def test_existing_create_only_receipt_is_an_idempotent_success() -> None:
    bucket = FakeBucket(exists=True)
    store = GCSMissionVerificationStore(bucket, journal=StubJournal(retained_entry()))

    receipt = store.verify("mission-001", "b" * 64, "verify-" + "a" * 40)

    assert receipt.head_hash == "b" * 64
    assert bucket.blobs[0].uploads[0][1]["if_generation_match"] == 0


def test_receipt_reader_returns_verified_content_or_pending() -> None:
    receipt_id = "verify-" + "a" * 40
    payload = json.dumps(
        {
            "cycle_id": "mission-001",
            "entry_count": 6,
            "head_hash": "b" * 64,
            "verification_id": receipt_id,
        }
    ).encode()
    reader = GCSVerificationReceiptReader(FakeBucket(exists=True, payload=payload))
    pending = GCSVerificationReceiptReader(FakeBucket())

    receipt = reader.read("mission-001", receipt_id)

    assert receipt is not None
    assert receipt.entry_count == 6
    assert receipt.sealed_at == "2026-08-12T20:30:03Z"
    assert pending.read("mission-001", receipt_id) is None


def test_receipt_reader_fails_closed_on_path_content_mismatch() -> None:
    receipt_id = "verify-" + "a" * 40
    payload = json.dumps(
        {
            "cycle_id": "other-mission",
            "entry_count": 6,
            "head_hash": "b" * 64,
            "verification_id": receipt_id,
        }
    ).encode()
    reader = GCSVerificationReceiptReader(FakeBucket(exists=True, payload=payload))

    with pytest.raises(JournalError, match="object path"):
        reader.read("mission-001", receipt_id)


@pytest.mark.parametrize(
    ("cycle_id", "head", "receipt_id", "message"),
    [
        ("../escape", "b" * 64, "verify-" + "a" * 40, "cycle_id"),
        ("mission-001", "f" * 64, "verify-" + "a" * 40, "head changed"),
        ("mission-001", "b" * 64, "attacker-path", "verification ID"),
    ],
)
def test_verification_refuses_untrusted_or_stale_identity(
    cycle_id: str,
    head: str,
    receipt_id: str,
    message: str,
) -> None:
    store = GCSMissionVerificationStore(FakeBucket(), journal=StubJournal(retained_entry()))

    with pytest.raises(JournalError, match=message):
        store.verify(cycle_id, head, receipt_id)
