from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from nightwatch.contracts import Stage
from nightwatch.followup import build_followup_draft
from nightwatch.journal import append_stage, read_journal
from nightwatch.mission_orchestrator import (
    SAFETY_270M_V1,
    SCAM_SAFETY_1B_V1,
    SCAM_SAFETY_LIVE_1B_V1,
)
from nightwatch.mission_service import create_control_app, create_worker_app
from nightwatch.mission_tasks import mission_task_id
from nightwatch.model_config import GEMMA_1B_MODEL_ID, GEMMA_1B_MODEL_REVISION
from nightwatch.operator_contracts import (
    InMemoryOperatorStore,
    build_followup_contract,
    build_mission_contract,
    mission_manifest_from_contract,
    parse_uploaded_dataset,
)


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


def test_worker_automatically_seals_followup_after_dynamic_refusal(tmp_path: Path) -> None:
    rows = [
        {"case": "t1", "message": "urgent transfer", "expected": "block", "suite": "target", "critical": False},
        {"case": "t2", "message": "verify invoice", "expected": "caution", "suite": "target", "critical": False},
        {"case": "r1", "message": "lunch ready", "expected": "routine", "suite": "regression", "critical": False},
        {"case": "r2", "message": "appointment tomorrow", "expected": "routine", "suite": "regression", "critical": False},
        {"case": "s1", "message": "send password", "expected": "block", "suite": "safety", "critical": True},
        {"case": "s2", "message": "use official app", "expected": "verify", "suite": "safety", "critical": False},
    ]
    dataset = parse_uploaded_dataset(
        ("\n".join(json.dumps(row) for row in rows) + "\n").encode(),
        "jsonl",
    )
    contract = build_mission_contract(
        {
            "subject": "scam message safety",
            "model": {"id": GEMMA_1B_MODEL_ID, "revision": GEMMA_1B_MODEL_REVISION},
            "baseline_artifact": "scam-v0-de1e6009-2d77e636-c0e947096d",
            "dataset_id": dataset.dataset_id,
            "mapping": {"id_column": "case", "text_column": "message", "label_column": "expected", "suite_column": "suite", "safety_critical_column": "critical"},
            "instruction": "Classify one received message by the safest immediate handling decision. Return exactly one label: block, caution, verify, or routine.",
            "policy": {"minimum_target_gain": 0.15, "maximum_regression_drop": 0.0, "minimum_safety_accuracy": 0.95, "require_zero_critical_misses": True},
            "compute": {"rank": 8, "epochs": 3.0, "learning_rate": 0.001, "seed": 20260813, "maximum_training_attempts": 1, "maximum_gpu_minutes": 20},
        },
        dataset,
    )
    store = InMemoryOperatorStore()
    store.create_dataset(dataset)
    store.create_contract(contract)
    journal = FileJournal(tmp_path / "dynamic-refusal.jsonl")
    cycle_id = "mission-dynamic-refusal"
    for stage, payload in [
        (Stage.CREATED, {"manifest_id": contract.contract_id}),
        (Stage.DIAGNOSED, {"manifest_id": contract.contract_id}),
        (Stage.CURRICULUM_READY, {"manifest_id": contract.contract_id}),
        (Stage.TRAINED, {"manifest_id": contract.contract_id}),
        (
            Stage.EVALUATED,
            {
                "manifest_id": contract.contract_id,
                "accepted": False,
                "artifact_sha256": "a" * 64,
                "decision": {
                    "accepted": False,
                    "failed_invariants": ["minimum_target_gain", "maximum_regression_drop"],
                },
            },
        ),
    ]:
        journal.append_stage(cycle_id, stage, payload)
    queue = FakeQueue()
    client = create_worker_app(
        journal=journal,
        executor=Executor(),
        task_queue=queue,
        manifest_resolver=lambda _manifest_id: mission_manifest_from_contract(contract),
        followup_store=store,
    ).test_client()
    task_id = mission_task_id(cycle_id, contract.contract_id, Stage.REJECTED)

    response = client.post(
        "/internal/tasks/advance-mission",
        json={
            "cycle_id": cycle_id,
            "expected_stage": Stage.REJECTED.value,
            "manifest_id": contract.contract_id,
        },
        headers={"X-CloudTasks-TaskName": task_id},
    )

    assert response.status_code == 200
    assert response.json["stage"] == Stage.REJECTED.value
    entries = journal.read_cycle(cycle_id)
    expected = build_followup_draft(cycle_id, entries, contract)
    persisted = store.read_followup(expected.draft_id)
    assert persisted == expected
    assert persisted.execution_authorized is False

    fresh_rows = [dict(row, message=f"{row['message']} rotated") for row in rows]
    fresh_dataset = parse_uploaded_dataset(
        ("\n".join(json.dumps(row) for row in fresh_rows) + "\n").encode(),
        "jsonl",
    )
    child = build_followup_contract(
        contract,
        fresh_dataset,
        expected,
        maximum_gpu_minutes=10,
    )
    store.create_dataset(fresh_dataset)
    store.create_contract(child)
    child_journal = FileJournal(tmp_path / "dynamic-child-refusal.jsonl")
    child_cycle_id = "mission-dynamic-child-refusal"
    for stage, payload in [
        (Stage.CREATED, {"manifest_id": child.contract_id}),
        (Stage.DIAGNOSED, {"manifest_id": child.contract_id}),
        (Stage.CURRICULUM_READY, {"manifest_id": child.contract_id}),
        (Stage.TRAINED, {"manifest_id": child.contract_id}),
        (
            Stage.EVALUATED,
            {
                "manifest_id": child.contract_id,
                "accepted": False,
                "artifact_sha256": "b" * 64,
                "decision": {
                    "accepted": False,
                    "failed_invariants": ["minimum_safety_accuracy"],
                },
            },
        ),
    ]:
        child_journal.append_stage(child_cycle_id, stage, payload)
    child_client = create_worker_app(
        journal=child_journal,
        executor=Executor(),
        task_queue=FakeQueue(),
        manifest_resolver=lambda _manifest_id: mission_manifest_from_contract(child),
        followup_store=store,
    ).test_client()

    child_response = child_client.post(
        "/internal/tasks/advance-mission",
        json={
            "cycle_id": child_cycle_id,
            "expected_stage": Stage.REJECTED.value,
            "manifest_id": child.contract_id,
        },
        headers={
            "X-CloudTasks-TaskName": mission_task_id(
                child_cycle_id,
                child.contract_id,
                Stage.REJECTED,
            )
        },
    )

    assert child_response.status_code == 200
    assert child_response.json["stage"] == Stage.REJECTED.value
    assert store.read_followup(expected.draft_id) == expected
