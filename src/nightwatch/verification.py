from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from nightwatch.firestore_journal import (
    FIRESTORE_TIMEOUT_SECONDS,
    FirestoreJournal,
    TransactionalDecorator,
    validate_cycle_id,
)
from nightwatch.journal import JournalError

_HEAD_HASH = re.compile(r"^[a-f0-9]{64}$")
_VERIFICATION_ID = re.compile(r"^verify-[a-f0-9]{40}$")


@dataclass(frozen=True)
class VerificationReceipt:
    verification_id: str
    cycle_id: str
    head_hash: str
    entry_count: int
    verified_at: str


def _receipt_from_data(value: dict[str, Any]) -> VerificationReceipt:
    try:
        receipt = VerificationReceipt(
            verification_id=str(value["verification_id"]),
            cycle_id=str(value["cycle_id"]),
            head_hash=str(value["head_hash"]),
            entry_count=int(value["entry_count"]),
            verified_at=str(value["verified_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise JournalError("verification receipt is malformed") from exc
    if (
        not _VERIFICATION_ID.fullmatch(receipt.verification_id)
        or not _HEAD_HASH.fullmatch(receipt.head_hash)
        or receipt.entry_count < 1
    ):
        raise JournalError("verification receipt is malformed")
    return receipt


class FirestoreMissionVerificationStore:
    def __init__(
        self,
        client: Any,
        *,
        journal: FirestoreJournal,
        transactional: TransactionalDecorator,
        collection: str = "missions",
    ) -> None:
        self._client = client
        self._journal = journal
        self._transactional = transactional
        self._collection = collection

    @classmethod
    def from_default(
        cls,
        *,
        project: str | None = None,
    ) -> FirestoreMissionVerificationStore:
        try:
            from google.cloud import firestore
        except ImportError as exc:
            raise RuntimeError("install the 'cloud' extra to use Firestore verification") from exc
        client = firestore.Client(project=project)
        journal = FirestoreJournal(client, transactional=firestore.transactional)
        return cls(client, journal=journal, transactional=firestore.transactional)

    def verify(
        self,
        cycle_id: str,
        expected_head_hash: str,
        verification_id: str,
        *,
        timestamp: str | None = None,
    ) -> VerificationReceipt:
        validate_cycle_id(cycle_id)
        if not _HEAD_HASH.fullmatch(expected_head_hash):
            raise JournalError("expected mission head must be a lowercase SHA-256 digest")
        if not _VERIFICATION_ID.fullmatch(verification_id):
            raise JournalError("verification ID is invalid")

        entries = self._journal.read_cycle(cycle_id)
        if not entries:
            raise JournalError("mission does not exist")
        if entries[-1].entry_hash != expected_head_hash:
            raise JournalError("mission head changed before verification")

        mission_ref = self._client.collection(self._collection).document(cycle_id)
        receipt_ref = mission_ref.collection("verifications").document(verification_id)
        transaction = self._client.transaction(max_attempts=5)
        verified_at = timestamp or datetime.now(timezone.utc).isoformat()

        @self._transactional
        def record(transaction: Any) -> VerificationReceipt:
            receipt_snapshot = receipt_ref.get(
                transaction=transaction,
                timeout=FIRESTORE_TIMEOUT_SECONDS,
            )
            mission_snapshot = mission_ref.get(
                transaction=transaction,
                timeout=FIRESTORE_TIMEOUT_SECONDS,
            )
            if receipt_snapshot.exists:
                existing = _receipt_from_data(receipt_snapshot.to_dict())
                if (
                    existing.cycle_id != cycle_id
                    or existing.head_hash != expected_head_hash
                    or existing.verification_id != verification_id
                ):
                    raise JournalError("verification receipt conflicts with this task")
                return existing
            if not mission_snapshot.exists:
                raise JournalError("mission disappeared during verification")
            mission = mission_snapshot.to_dict()
            if (
                mission.get("head_hash") != expected_head_hash
                or mission.get("entry_count") != len(entries)
            ):
                raise JournalError("mission head changed during verification")
            receipt = VerificationReceipt(
                verification_id=verification_id,
                cycle_id=cycle_id,
                head_hash=expected_head_hash,
                entry_count=len(entries),
                verified_at=verified_at,
            )
            data = asdict(receipt)
            transaction.set(receipt_ref, data)
            transaction.set(mission_ref, {"last_verification": data}, merge=True)
            return receipt

        return record(transaction)
