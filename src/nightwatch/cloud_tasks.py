from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from google.api_core.exceptions import AlreadyExists

from nightwatch.firestore_journal import validate_cycle_id
from nightwatch.journal import JournalError

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_HEAD_HASH = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class ScheduledVerification:
    task_name: str
    verification_id: str
    duplicate: bool


def validate_idempotency_key(value: str) -> None:
    if not _IDEMPOTENCY_KEY.fullmatch(value):
        raise JournalError(
            "idempotency key must contain 8-128 letters, digits, dots, underscores, colons, or hyphens"
        )


def verification_id(cycle_id: str, head_hash: str, idempotency_key: str) -> str:
    validate_cycle_id(cycle_id)
    validate_idempotency_key(idempotency_key)
    if not _HEAD_HASH.fullmatch(head_hash):
        raise JournalError("expected mission head must be a lowercase SHA-256 digest")
    material = f"{cycle_id}\n{head_hash}\n{idempotency_key}".encode("utf-8")
    return f"verify-{hashlib.sha256(material).hexdigest()[:40]}"


class CloudTasksVerificationQueue:
    def __init__(
        self,
        client: Any,
        *,
        project: str,
        location: str,
        queue: str,
        worker_url: str,
        invoker_service_account: str,
    ) -> None:
        if not worker_url.startswith("https://"):
            raise ValueError("Cloud Tasks worker URL must use HTTPS")
        self._client = client
        self._project = project
        self._location = location
        self._queue = queue
        self._worker_url = worker_url.rstrip("/")
        self._invoker_service_account = invoker_service_account

    @classmethod
    def from_default(
        cls,
        *,
        project: str,
        location: str,
        queue: str,
        worker_url: str,
        invoker_service_account: str,
    ) -> CloudTasksVerificationQueue:
        try:
            from google.cloud import tasks_v2
        except ImportError as exc:
            raise RuntimeError("install the 'cloud' extra to use Cloud Tasks") from exc
        return cls(
            tasks_v2.CloudTasksClient(),
            project=project,
            location=location,
            queue=queue,
            worker_url=worker_url,
            invoker_service_account=invoker_service_account,
        )

    def enqueue_verification(
        self,
        cycle_id: str,
        head_hash: str,
        idempotency_key: str,
    ) -> ScheduledVerification:
        from google.cloud import tasks_v2

        receipt_id = verification_id(cycle_id, head_hash, idempotency_key)
        parent = self._client.queue_path(self._project, self._location, self._queue)
        task_name = self._client.task_path(
            self._project,
            self._location,
            self._queue,
            receipt_id,
        )
        payload = json.dumps(
            {
                "cycle_id": cycle_id,
                "expected_head_hash": head_hash,
                "verification_id": receipt_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        task = tasks_v2.Task(
            name=task_name,
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=f"{self._worker_url}/internal/tasks/verify-mission",
                headers={"Content-Type": "application/json"},
                body=payload,
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self._invoker_service_account,
                    audience=self._worker_url,
                ),
            ),
        )
        try:
            created = self._client.create_task(parent=parent, task=task)
        except AlreadyExists:
            return ScheduledVerification(task_name, receipt_id, True)
        return ScheduledVerification(created.name, receipt_id, False)
