from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from google.api_core.exceptions import Conflict, PreconditionFailed

from nightwatch.firestore_journal import FirestoreJournal, validate_cycle_id
from nightwatch.journal import JournalError

_HEAD_HASH = re.compile(r"^[a-f0-9]{64}$")
_VERIFICATION_ID = re.compile(r"^verify-[a-f0-9]{40}$")
GCS_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class VerificationReceipt:
    verification_id: str
    cycle_id: str
    head_hash: str
    entry_count: int


class GCSMissionVerificationStore:
    """Validate Firestore evidence and create one immutable receipt object.

    A retry uses the same content-derived object name and succeeds when the
    generation-zero precondition reports that the receipt already exists. The
    worker therefore needs objectCreator, never objectViewer or objectAdmin.
    """

    def __init__(self, bucket: Any, *, journal: FirestoreJournal) -> None:
        self._bucket = bucket
        self._journal = journal

    @classmethod
    def from_default(
        cls,
        *,
        project: str | None,
        bucket_name: str,
    ) -> GCSMissionVerificationStore:
        try:
            from google.cloud import firestore, storage
        except ImportError as exc:
            raise RuntimeError("install the 'service' extra to verify missions") from exc
        firestore_client = firestore.Client(project=project)
        journal = FirestoreJournal(
            firestore_client,
            transactional=firestore.transactional,
        )
        storage_client = storage.Client(project=project)
        return cls(storage_client.bucket(bucket_name), journal=journal)

    def verify(
        self,
        cycle_id: str,
        expected_head_hash: str,
        verification_id: str,
        *,
        timestamp: str | None = None,
    ) -> VerificationReceipt:
        del timestamp  # GCS timeCreated is the authoritative receipt timestamp.
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

        receipt = VerificationReceipt(
            verification_id=verification_id,
            cycle_id=cycle_id,
            head_hash=expected_head_hash,
            entry_count=len(entries),
        )
        payload = json.dumps(
            asdict(receipt),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        blob = self._bucket.blob(
            f"verifications/{cycle_id}/{verification_id}.json"
        )
        try:
            blob.upload_from_string(
                payload,
                content_type="application/json",
                if_generation_match=0,
                timeout=GCS_TIMEOUT_SECONDS,
            )
        except (Conflict, PreconditionFailed):
            # The object name and bytes are both derived from validated inputs;
            # create-only IAM means an existing object is the same completed effect.
            pass
        return receipt
