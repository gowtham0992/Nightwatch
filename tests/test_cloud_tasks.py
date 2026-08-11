from __future__ import annotations

import json

import pytest
from google.api_core.exceptions import AlreadyExists

from nightwatch.cloud_tasks import CloudTasksVerificationQueue, verification_id
from nightwatch.journal import JournalError


class FakeTasksClient:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.created: list[tuple[str, object]] = []

    def queue_path(self, project: str, location: str, queue: str) -> str:
        return f"projects/{project}/locations/{location}/queues/{queue}"

    def task_path(self, project: str, location: str, queue: str, task: str) -> str:
        return f"{self.queue_path(project, location, queue)}/tasks/{task}"

    def create_task(self, *, parent: str, task: object) -> object:
        self.created.append((parent, task))
        if self.duplicate:
            raise AlreadyExists("already queued")
        return type("CreatedTask", (), {"name": task.name})()


def make_queue(client: FakeTasksClient) -> CloudTasksVerificationQueue:
    return CloudTasksVerificationQueue(
        client,
        project="project-1",
        location="us-central1",
        queue="nightwatch-verifications",
        worker_url="https://worker.example.run.app",
        invoker_service_account="nightwatch-tasks@project-1.iam.gserviceaccount.com",
    )


def test_named_task_is_deterministic_and_oidc_authenticated() -> None:
    client = FakeTasksClient()
    queue = make_queue(client)
    head = "a" * 64

    scheduled = queue.enqueue_verification("mission-001", head, "operator:request-001")

    assert scheduled.verification_id == verification_id(
        "mission-001", head, "operator:request-001"
    )
    assert scheduled.task_name.endswith(f"/tasks/{scheduled.verification_id}")
    assert scheduled.duplicate is False
    parent, task = client.created[0]
    assert parent.endswith("/queues/nightwatch-verifications")
    assert task.http_request.url == "https://worker.example.run.app/internal/tasks/verify-mission"
    assert task.http_request.oidc_token.audience == "https://worker.example.run.app"
    assert task.http_request.oidc_token.service_account_email == (
        "nightwatch-tasks@project-1.iam.gserviceaccount.com"
    )
    assert json.loads(task.http_request.body) == {
        "cycle_id": "mission-001",
        "expected_head_hash": head,
        "verification_id": scheduled.verification_id,
    }


def test_duplicate_task_is_reported_as_same_effect() -> None:
    queue = make_queue(FakeTasksClient(duplicate=True))

    scheduled = queue.enqueue_verification(
        "mission-001", "b" * 64, "operator:request-001"
    )

    assert scheduled.duplicate is True
    assert scheduled.task_name.endswith(f"/tasks/{scheduled.verification_id}")


@pytest.mark.parametrize(
    ("cycle_id", "head", "key"),
    [
        ("../escape", "a" * 64, "operator:request-001"),
        ("mission-001", "not-a-hash", "operator:request-001"),
        ("mission-001", "a" * 64, "short"),
        ("mission-001", "a" * 64, "operator/request-001"),
    ],
)
def test_task_identity_rejects_untrusted_identifiers(
    cycle_id: str,
    head: str,
    key: str,
) -> None:
    with pytest.raises(JournalError):
        verification_id(cycle_id, head, key)


def test_worker_url_must_be_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        CloudTasksVerificationQueue(
            FakeTasksClient(),
            project="project-1",
            location="us-central1",
            queue="nightwatch-verifications",
            worker_url="http://worker.invalid",
            invoker_service_account="worker@example.invalid",
        )
