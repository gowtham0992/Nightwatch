from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.protobuf import duration_pb2

from nightwatch.contracts import Stage
from nightwatch.firestore_journal import validate_cycle_id
from nightwatch.mission_orchestrator import validate_manifest_id

MISSION_TASK_DEADLINE_SECONDS = 30 * 60


@dataclass(frozen=True)
class ScheduledMissionStage:
    task_name: str
    task_id: str
    duplicate: bool


def mission_task_id(cycle_id: str, manifest_id: str, expected_stage: Stage) -> str:
    validate_cycle_id(cycle_id)
    validate_manifest_id(manifest_id)
    material = f"{cycle_id}\n{manifest_id}\n{expected_stage.value}".encode()
    return f"mission-{hashlib.sha256(material).hexdigest()[:40]}"


class CloudTasksMissionQueue:
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
            raise ValueError("Cloud Tasks mission worker URL must use HTTPS")
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
    ) -> CloudTasksMissionQueue:
        try:
            from google.cloud import tasks_v2
        except ImportError as exc:
            raise RuntimeError("install the 'cloud' extra to use the mission queue") from exc
        return cls(
            tasks_v2.CloudTasksClient(),
            project=project,
            location=location,
            queue=queue,
            worker_url=worker_url,
            invoker_service_account=invoker_service_account,
        )

    def enqueue_stage(
        self,
        cycle_id: str,
        manifest_id: str,
        expected_stage: Stage,
    ) -> ScheduledMissionStage:
        from google.cloud import tasks_v2

        task_id = mission_task_id(cycle_id, manifest_id, expected_stage)
        parent = self._client.queue_path(self._project, self._location, self._queue)
        task_name = self._client.task_path(
            self._project,
            self._location,
            self._queue,
            task_id,
        )
        payload = json.dumps(
            {
                "cycle_id": cycle_id,
                "expected_stage": expected_stage.value,
                "manifest_id": manifest_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        task = tasks_v2.Task(
            name=task_name,
            dispatch_deadline=duration_pb2.Duration(seconds=MISSION_TASK_DEADLINE_SECONDS),
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=f"{self._worker_url}/internal/tasks/advance-mission",
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
            return ScheduledMissionStage(task_name, task_id, True)
        return ScheduledMissionStage(created.name, task_id, False)
