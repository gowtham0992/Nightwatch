from __future__ import annotations

import json

from google.api_core.exceptions import AlreadyExists

from nightwatch.contracts import Stage
from nightwatch.mission_orchestrator import SAFETY_270M_V1
from nightwatch.mission_tasks import (
    MISSION_TASK_GENERATION,
    CloudTasksMissionQueue,
    mission_task_id,
)


class FakeClient:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.created = []

    def queue_path(self, project, location, queue):
        return f"projects/{project}/locations/{location}/queues/{queue}"

    def task_path(self, project, location, queue, task):
        return f"projects/{project}/locations/{location}/queues/{queue}/tasks/{task}"

    def create_task(self, *, parent, task):
        self.created.append((parent, task))
        if self.duplicate:
            raise AlreadyExists("exists")

        class Created:
            name = task.name

        return Created()


def queue(client: FakeClient) -> CloudTasksMissionQueue:
    return CloudTasksMissionQueue(
        client,
        project="nightwatch-agentic-0992",
        location="us-central1",
        queue="nightwatch-missions",
        worker_url="https://nightwatch-mission-worker.example.run.app",
        invoker_service_account="nightwatch-missions-invoker@example.iam.gserviceaccount.com",
    )


def test_stage_task_is_oidc_bound_with_deterministic_name_and_30_minute_deadline() -> None:
    assert MISSION_TASK_GENERATION == "g2"
    client = FakeClient()
    scheduled = queue(client).enqueue_stage(
        "mission-live-301",
        SAFETY_270M_V1.manifest_id,
        Stage.TRAINED,
    )

    parent, task = client.created[0]
    body = json.loads(task.http_request.body)
    assert parent.endswith("/queues/nightwatch-missions")
    assert scheduled.task_id == mission_task_id(
        "mission-live-301", SAFETY_270M_V1.manifest_id, Stage.TRAINED
    )
    assert task.name.endswith(scheduled.task_id)
    assert task.dispatch_deadline.seconds == 1800
    assert task.http_request.url.endswith("/internal/tasks/advance-mission")
    assert task.http_request.oidc_token.audience == (
        "https://nightwatch-mission-worker.example.run.app"
    )
    assert body == {
        "cycle_id": "mission-live-301",
        "expected_stage": "trained",
        "manifest_id": SAFETY_270M_V1.manifest_id,
    }


def test_duplicate_stage_task_is_idempotent_success() -> None:
    scheduled = queue(FakeClient(duplicate=True)).enqueue_stage(
        "mission-live-302",
        SAFETY_270M_V1.manifest_id,
        Stage.CREATED,
    )

    assert scheduled.duplicate is True
