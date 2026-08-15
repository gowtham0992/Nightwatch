from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nightwatch.contracts import Stage
from nightwatch.journal import append_stage, read_journal
from nightwatch.mission_orchestrator import (
    SAFETY_270M_V1,
    SCAM_SAFETY_1B_V1,
    SCAM_SAFETY_LIVE_1B_V1,
)
from nightwatch.mission_service import create_control_app, create_worker_app
from nightwatch.mission_tasks import mission_task_id


@dataclass
class Scheduled:
    task_id: str
    duplicate: bool = False


class FakeQueue:
    def __init__(self) -> None:
        self.calls = []

    def enqueue_stage(self, cycle_id, manifest_id, expected_stage):
        self.calls.append((cycle_id, manifest_id, expected_stage))
        return Scheduled(mission_task_id(cycle_id, manifest_id, expected_stage))


class FileJournal:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read_cycle(self, cycle_id):
        return [entry for entry in read_journal(self.path) if entry.cycle_id == cycle_id]

    def append_stage(self, cycle_id, stage, payload, *, timestamp=None):
        return append_stage(self.path, cycle_id, stage, payload, timestamp=timestamp)


class Executor:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, cycle_id, stage, manifest, entries):
        self.calls.append(stage)
        return {"manifest_id": manifest.manifest_id, "proof": stage.value}


def test_control_accepts_only_approved_bounded_manifest() -> None:
    queue = FakeQueue()
    client = create_control_app(task_queue=queue).test_client()

    response = client.post(
        "/api/missions",
        json={
            "cycle_id": "mission-live-401",
            "manifest_id": SAFETY_270M_V1.manifest_id,
        },
    )
    injected = client.post(
        "/api/missions",
        json={
            "cycle_id": "mission-live-402",
            "manifest_id": SAFETY_270M_V1.manifest_id,
            "model_id": "attacker/model",
        },
    )

    assert response.status_code == 202
    assert response.json["status"] == "queued"
    assert queue.calls == [
        ("mission-live-401", SAFETY_270M_V1.manifest_id, Stage.CREATED)
    ]
    assert injected.status_code == 400


def test_control_accepts_the_fixed_scam_safety_manifest() -> None:
    queue = FakeQueue()
    client = create_control_app(task_queue=queue).test_client()

    response = client.post(
        "/api/missions",
        json={
            "cycle_id": "mission-scam-service-001",
            "manifest_id": SCAM_SAFETY_1B_V1.manifest_id,
        },
    )

    assert response.status_code == 202
    assert queue.calls == [
        ("mission-scam-service-001", SCAM_SAFETY_1B_V1.manifest_id, Stage.CREATED)
    ]


def test_control_accepts_the_fixed_live_agent_scam_manifest() -> None:
    queue = FakeQueue()
    client = create_control_app(task_queue=queue).test_client()

    response = client.post(
        "/api/missions",
        json={
            "cycle_id": "mission-scam-live-001",
            "manifest_id": SCAM_SAFETY_LIVE_1B_V1.manifest_id,
        },
    )

    assert response.status_code == 202
    assert queue.calls == [
        (
            "mission-scam-live-001",
            SCAM_SAFETY_LIVE_1B_V1.manifest_id,
            Stage.CREATED,
        )
    ]


def test_worker_advances_bound_stage_once_and_enqueues_next(tmp_path: Path) -> None:
    journal = FileJournal(tmp_path / "mission.jsonl")
    executor = Executor()
    queue = FakeQueue()
    client = create_worker_app(
        journal=journal,
        executor=executor,
        task_queue=queue,
    ).test_client()
    task_id = mission_task_id(
        "mission-live-403", SAFETY_270M_V1.manifest_id, Stage.CREATED
    )
    body = {
        "cycle_id": "mission-live-403",
        "expected_stage": "created",
        "manifest_id": SAFETY_270M_V1.manifest_id,
    }

    first = client.post(
        "/internal/tasks/advance-mission",
        json=body,
        headers={"X-CloudTasks-TaskName": task_id},
    )
    replay = client.post(
        "/internal/tasks/advance-mission",
        json=body,
        headers={"X-CloudTasks-TaskName": task_id},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json["stage"] == "created"
    assert first.json["next_stage"] == "diagnosed"
    assert executor.calls == []
    assert [entry.stage for entry in journal.read_cycle("mission-live-403")] == [Stage.CREATED]
    assert queue.calls == [
        ("mission-live-403", SAFETY_270M_V1.manifest_id, Stage.DIAGNOSED),
        ("mission-live-403", SAFETY_270M_V1.manifest_id, Stage.DIAGNOSED),
    ]


def test_worker_rejects_missing_or_mismatched_cloud_task_identity(tmp_path: Path) -> None:
    client = create_worker_app(
        journal=FileJournal(tmp_path / "mission.jsonl"),
        executor=Executor(),
        task_queue=FakeQueue(),
    ).test_client()
    body = {
        "cycle_id": "mission-live-404",
        "expected_stage": "created",
        "manifest_id": SAFETY_270M_V1.manifest_id,
    }

    missing = client.post("/internal/tasks/advance-mission", json=body)
    wrong = client.post(
        "/internal/tasks/advance-mission",
        json=body,
        headers={"X-CloudTasks-TaskName": "mission-attacker"},
    )

    assert missing.status_code == 400
    assert wrong.status_code == 400
