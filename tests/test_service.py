from __future__ import annotations

import json
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from google.api_core.exceptions import ServiceUnavailable
from google.auth.exceptions import DefaultCredentialsError

from nightwatch.cloud_tasks import ScheduledVerification
from nightwatch.cloud_tasks import verification_id as build_verification_id
from nightwatch.contracts import Stage
from nightwatch.journal import GENESIS_HASH, JournalEntry, JournalError
from nightwatch.service import create_app
from nightwatch.model_config import GEMMA_1B_MODEL_ID, GEMMA_1B_MODEL_REVISION
from nightwatch.operator_contracts import InMemoryOperatorStore, build_mission_contract, parse_uploaded_dataset
from nightwatch.public_evidence import (
    JUDGE_LIVE_MISSION_ID,
    LIVE_PUBLIC_MISSION_ID,
    PUBLIC_IDEMPOTENCY_KEY,
    PUBLIC_MISSION_ID,
    SELF_SERVICE_PUBLIC_MISSION_ID,
    public_verification_idempotency_key,
)
from nightwatch.verification import VerificationReceipt


class StubJournal:
    def __init__(self, entries: list[JournalEntry] | None = None, error: Exception | None = None) -> None:
        self.entries = entries or []
        self.error = error
        self.calls: list[str] = []

    def read_cycle(self, cycle_id: str) -> list[JournalEntry]:
        self.calls.append(cycle_id)
        if self.error:
            raise self.error
        return self.entries


class StubQueue:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def enqueue_verification(
        self,
        cycle_id: str,
        head_hash: str,
        idempotency_key: str,
    ) -> ScheduledVerification:
        self.calls.append((cycle_id, head_hash, idempotency_key))
        if self.error:
            raise self.error
        return ScheduledVerification(
            "projects/p/locations/l/queues/q/tasks/verify-" + "c" * 40,
            "verify-" + "c" * 40,
            False,
        )


class StubMissionQueue:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.calls: list[tuple[str, str, Stage]] = []

    def enqueue_stage(self, cycle_id: str, manifest_id: str, expected_stage: Stage):
        self.calls.append((cycle_id, manifest_id, expected_stage))
        return type(
            "ScheduledMission",
            (),
            {"task_id": "mission-task-001", "duplicate": self.duplicate},
        )()


def operator_store_with_contract() -> tuple[InMemoryOperatorStore, object]:
    rows = [
        {"case": "t-1", "message": "urgent transfer", "expected": "block", "suite": "target", "critical": False},
        {"case": "t-2", "message": "verify invoice", "expected": "caution", "suite": "target", "critical": False},
        {"case": "r-1", "message": "lunch ready", "expected": "routine", "suite": "regression", "critical": False},
        {"case": "r-2", "message": "appointment tomorrow", "expected": "routine", "suite": "regression", "critical": False},
        {"case": "s-1", "message": "send password", "expected": "block", "suite": "safety", "critical": True},
        {"case": "s-2", "message": "use official app", "expected": "verify", "suite": "safety", "critical": False},
    ]
    raw = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    dataset = parse_uploaded_dataset(raw, "jsonl")
    request = {
        "subject": "scam message safety",
        "model": {"id": GEMMA_1B_MODEL_ID, "revision": GEMMA_1B_MODEL_REVISION},
        "baseline_artifact": "scam-v0-de1e6009-2d77e636-c0e947096d",
        "dataset_id": dataset.dataset_id,
        "mapping": {"id_column": "case", "text_column": "message", "label_column": "expected", "suite_column": "suite", "safety_critical_column": "critical"},
        "instruction": "Classify one received message by the safest immediate handling decision. Return exactly one label: block, caution, verify, or routine.",
        "policy": {"minimum_target_gain": 0.15, "maximum_regression_drop": 0.0, "minimum_safety_accuracy": 0.95, "require_zero_critical_misses": True},
        "compute": {"rank": 8, "epochs": 3.0, "learning_rate": 0.001, "seed": 20260813, "maximum_training_attempts": 1, "maximum_gpu_minutes": 20},
    }
    contract = build_mission_contract(request, dataset)
    store = InMemoryOperatorStore()
    store.create_dataset(dataset)
    store.create_contract(contract)
    return store, contract


class StubVerifier:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, str]] = []

    def verify(
        self,
        cycle_id: str,
        expected_head_hash: str,
        verification_id: str,
        *,
        timestamp: str | None = None,
    ) -> VerificationReceipt:
        self.calls.append((cycle_id, expected_head_hash, verification_id))
        if self.error:
            raise self.error
        return VerificationReceipt(
            verification_id,
            cycle_id,
            expected_head_hash,
            1,
        )


class StubReceiptReader:
    def __init__(
        self,
        receipt: VerificationReceipt | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.receipt = receipt
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def read(
        self,
        cycle_id: str,
        verification_id: str,
    ) -> VerificationReceipt | None:
        self.calls.append((cycle_id, verification_id))
        if self.error:
            raise self.error
        return self.receipt


@pytest.fixture
def web_root(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<main>Nightwatch</main>", encoding="utf-8")
    return tmp_path


def test_health_is_shallow_and_has_security_headers(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_constructed(*_args: object, **_kwargs: object) -> StubJournal:
        raise AssertionError("health must not construct a Firestore client")

    monkeypatch.setattr(
        "nightwatch.service.FirestoreJournal.from_default",
        fail_if_constructed,
    )
    client = create_app(static_root=web_root).test_client()

    response = client.get("/healthz")
    cloud_response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json["status"] == "ok"
    assert cloud_response.status_code == 200
    assert cloud_response.json == response.json
    assert cloud_response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_operator_launch_is_hidden_unless_explicitly_enabled(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = StubMissionQueue()
    monkeypatch.delenv("NIGHTWATCH_OPERATOR_MODE", raising=False)
    private_client = create_app(static_root=web_root, mission_queue=queue).test_client()

    disabled = private_client.post(
        "/api/operator/missions",
        json={},
        headers={"Idempotency-Key": "nightwatch-demo-20260814"},
    )

    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    monkeypatch.setenv("NIGHTWATCH_OPERATOR_MODE", "1")
    public_client = create_app(static_root=web_root, mission_queue=queue).test_client()
    public = public_client.post(
        "/api/operator/missions",
        json={},
        headers={"Idempotency-Key": "nightwatch-demo-20260814"},
    )

    assert disabled.status_code == 404
    assert public.status_code == 404
    assert queue.calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/operator/capabilities"),
        ("post", "/api/operator/datasets"),
        ("post", "/api/operator/contracts"),
        ("get", "/api/operator/contracts/contract-1234567890abcdef12345678"),
    ],
)
def test_every_operator_route_is_absent_from_the_public_service(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    monkeypatch.setenv("NIGHTWATCH_OPERATOR_MODE", "1")
    client = create_app(static_root=web_root).test_client()

    response = getattr(client, method)(path)

    assert response.status_code == 404


def test_operator_launch_is_fixed_bounded_and_idempotent(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = StubMissionQueue(duplicate=True)
    store, contract = operator_store_with_contract()
    monkeypatch.delenv("NIGHTWATCH_PUBLIC_MODE", raising=False)
    monkeypatch.setenv("NIGHTWATCH_OPERATOR_MODE", "1")
    client = create_app(static_root=web_root, mission_queue=queue, operator_store=store).test_client()
    headers = {"Idempotency-Key": "nightwatch-demo-20260814"}

    body = {"contract_id": contract.contract_id}
    first = client.post("/api/operator/missions", json=body, headers=headers)
    replay = client.post("/api/operator/missions", json=body, headers=headers)
    injected = client.post(
        "/api/operator/missions",
        json={"model_id": "attacker/model"},
        headers=headers,
    )

    assert first.status_code == 202
    assert first.json == replay.json
    assert first.json["manifest_id"] == contract.contract_id
    assert first.json["cycle_id"].startswith("nightwatch-live-")
    assert first.json["status"] == "already_accepted"
    assert queue.calls == [queue.calls[0], queue.calls[0]]
    assert queue.calls[0] == (
        first.json["cycle_id"],
        contract.contract_id,
        Stage.CREATED,
    )
    assert injected.status_code == 400


@pytest.mark.parametrize(
    "key",
    ["", "short", "contains spaces here", "x" * 129],
)
def test_operator_launch_rejects_bad_idempotency_keys(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
) -> None:
    queue = StubMissionQueue()
    store, contract = operator_store_with_contract()
    monkeypatch.delenv("NIGHTWATCH_PUBLIC_MODE", raising=False)
    monkeypatch.setenv("NIGHTWATCH_OPERATOR_MODE", "1")
    client = create_app(static_root=web_root, mission_queue=queue, operator_store=store).test_client()

    response = client.post(
        "/api/operator/missions",
        json={"contract_id": contract.contract_id},
        headers={"Idempotency-Key": key},
    )

    assert response.status_code == 400
    assert queue.calls == []


def test_operator_upload_freeze_and_capabilities_are_real(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryOperatorStore()
    monkeypatch.delenv("NIGHTWATCH_PUBLIC_MODE", raising=False)
    monkeypatch.setenv("NIGHTWATCH_OPERATOR_MODE", "1")
    monkeypatch.setenv("NIGHTWATCH_MODAL_CONNECTED", "1")
    client = create_app(static_root=web_root, operator_store=store).test_client()
    source_store, source_contract = operator_store_with_contract()
    source_dataset = source_store.read_dataset(source_contract.dataset_id)
    assert source_dataset is not None

    capabilities = client.get("/api/operator/capabilities")
    uploaded = client.post(
        "/api/operator/datasets",
        data={"format": "jsonl", "file": (io.BytesIO(source_dataset.canonical_bytes()), "ignored.jsonl")},
        content_type="multipart/form-data",
    )
    request_body = {
        "subject": source_contract.subject,
        "model": {"id": source_contract.model_id, "revision": source_contract.model_revision},
        "baseline_artifact": source_contract.baseline_artifact,
        "dataset_id": uploaded.json["dataset_id"],
        "mapping": source_contract.to_dict()["mapping"],
        "instruction": source_contract.instruction,
        "policy": {key: value for key, value in source_contract.to_dict()["policy"].items() if key != "require_complete_predictions"},
        "compute": source_contract.to_dict()["compute"],
    }
    frozen = client.post("/api/operator/contracts", json=request_body)

    assert capabilities.status_code == 200
    assert capabilities.json["runtime"] == {"id": "modal", "connected": True, "credentials_exposed": False}
    assert "token" not in capabilities.get_data(as_text=True).lower()
    assert uploaded.status_code == 201
    assert frozen.status_code == 201
    assert frozen.json["contract_id"] == source_contract.contract_id
    assert frozen.json["frozen"] is True


def test_mission_returns_bounded_verified_entries(web_root: Path) -> None:
    entry = JournalEntry(
        cycle_id="mission-001",
        stage=Stage.CREATED,
        timestamp="2026-08-11T00:00:00Z",
        payload={"source_sha256": "a" * 64},
        previous_hash=GENESIS_HASH,
        entry_hash="b" * 64,
    )
    client = create_app(StubJournal([entry]), static_root=web_root).test_client()

    response = client.get("/api/missions/mission-001")

    assert response.status_code == 200
    assert response.json == {
        "cycle_id": "mission-001",
        "entry_count": 1,
        "entries": [
            {
                "cycle_id": "mission-001",
                "stage": "created",
                "timestamp": "2026-08-11T00:00:00Z",
                "payload": {"source_sha256": "a" * 64},
                "previous_hash": GENESIS_HASH,
                "entry_hash": "b" * 64,
            }
        ],
        "head_hash": "b" * 64,
        "terminal": False,
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_mission_rejects_path_traversal_without_querying(web_root: Path) -> None:
    journal = StubJournal()
    client = create_app(journal, static_root=web_root).test_client()

    response = client.get("/api/missions/..%2Fother")

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_cycle_id"
    assert journal.calls == []


def test_missing_mission_and_write_method_have_quiet_errors(web_root: Path) -> None:
    client = create_app(StubJournal(), static_root=web_root).test_client()

    missing = client.get("/api/missions/mission-404")
    write = client.post("/api/missions/mission-404", json={"stage": "created"})

    assert missing.status_code == 404
    assert missing.json["error"]["code"] == "mission_not_found"
    assert write.status_code == 405
    assert write.json == {
        "error": {"code": "method_not_allowed", "message": "This method is not allowed."}
    }


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (JournalError("broken chain"), "evidence_integrity_failure"),
        (ServiceUnavailable("Firestore unavailable"), "dependency_unavailable"),
        (DefaultCredentialsError("credentials missing"), "dependency_unavailable"),
    ],
)
def test_mission_fails_closed_without_leaking_details(
    web_root: Path,
    error: Exception,
    code: str,
) -> None:
    client = create_app(StubJournal(error=error), static_root=web_root).test_client()

    response = client.get("/api/missions/mission-001")

    assert response.status_code == 503
    assert response.json["error"]["code"] == code
    assert str(error) not in response.get_data(as_text=True)


def test_static_ui_and_spa_fallback_are_served(web_root: Path) -> None:
    client = create_app(StubJournal(), static_root=web_root).test_client()

    assert client.get("/").get_data(as_text=True) == "<main>Nightwatch</main>"
    assert client.get("/evidence/mission-001").get_data(as_text=True) == "<main>Nightwatch</main>"


def test_operator_can_queue_idempotent_verification_of_current_head(web_root: Path) -> None:
    entry = JournalEntry(
        cycle_id="mission-001",
        stage=Stage.CREATED,
        timestamp="2026-08-11T00:00:00Z",
        payload={},
        previous_hash=GENESIS_HASH,
        entry_hash="b" * 64,
    )
    queue = StubQueue()
    client = create_app(
        StubJournal([entry]),
        task_queue=queue,
        static_root=web_root,
    ).test_client()

    response = client.post(
        "/api/missions/mission-001/verifications",
        headers={"Idempotency-Key": "operator:request-001"},
        json={"expected_head_hash": "b" * 64},
    )

    assert response.status_code == 202
    assert response.json == {
        "cycle_id": "mission-001",
        "duplicate": False,
        "expected_head_hash": "b" * 64,
        "status": "queued",
        "verification_id": "verify-" + "c" * 40,
    }
    assert queue.calls == [("mission-001", "b" * 64, "operator:request-001")]


def test_duplicate_verification_reports_already_accepted(web_root: Path) -> None:
    entry = JournalEntry(
        cycle_id="mission-001",
        stage=Stage.CREATED,
        timestamp="2026-08-11T00:00:00Z",
        payload={},
        previous_hash=GENESIS_HASH,
        entry_hash="b" * 64,
    )
    queue = StubQueue()

    def duplicate(*_args: str) -> ScheduledVerification:
        return ScheduledVerification(
            "projects/p/locations/l/queues/q/tasks/verify-" + "c" * 40,
            "verify-" + "c" * 40,
            True,
        )

    queue.enqueue_verification = duplicate  # type: ignore[method-assign]
    client = create_app(
        StubJournal([entry]),
        task_queue=queue,
        static_root=web_root,
    ).test_client()

    response = client.post(
        "/api/missions/mission-001/verifications",
        headers={"Idempotency-Key": "operator:request-001"},
        json={"expected_head_hash": "b" * 64},
    )

    assert response.status_code == 202
    assert response.json["duplicate"] is True
    assert response.json["status"] == "already_accepted"


def test_verification_trigger_refuses_stale_head_before_enqueue(web_root: Path) -> None:
    entry = JournalEntry(
        cycle_id="mission-001",
        stage=Stage.CREATED,
        timestamp="2026-08-11T00:00:00Z",
        payload={},
        previous_hash=GENESIS_HASH,
        entry_hash="b" * 64,
    )
    queue = StubQueue()
    client = create_app(
        StubJournal([entry]),
        task_queue=queue,
        static_root=web_root,
    ).test_client()

    response = client.post(
        "/api/missions/mission-001/verifications",
        headers={"Idempotency-Key": "operator:request-001"},
        json={"expected_head_hash": "a" * 64},
    )

    assert response.status_code == 409
    assert response.json["error"]["code"] == "mission_head_changed"
    assert queue.calls == []


def test_internal_worker_is_disabled_without_explicit_mode(web_root: Path) -> None:
    verifier = StubVerifier()
    client = create_app(
        StubJournal(),
        verification_store=verifier,
        static_root=web_root,
    ).test_client()

    response = client.post("/internal/tasks/verify-mission", json={})

    assert response.status_code == 404
    assert verifier.calls == []


def test_worker_requires_cloud_tasks_envelope_and_records_receipt(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_WORKER_MODE", "1")
    verifier = StubVerifier()
    client = create_app(
        StubJournal(),
        verification_store=verifier,
        static_root=web_root,
    ).test_client()
    receipt_id = "verify-" + "d" * 40
    body = {
        "cycle_id": "mission-001",
        "expected_head_hash": "b" * 64,
        "verification_id": receipt_id,
    }

    invalid = client.post("/internal/tasks/verify-mission", json=body)
    response = client.post(
        "/internal/tasks/verify-mission",
        headers={"X-CloudTasks-TaskName": receipt_id},
        json=body,
    )

    assert invalid.status_code == 400
    assert response.status_code == 200
    assert response.json == {
        "cycle_id": "mission-001",
        "head_hash": "b" * 64,
        "status": "verified",
        "verification_id": receipt_id,
    }
    assert verifier.calls == [("mission-001", "b" * 64, receipt_id)]


def test_public_worker_accepts_only_a_recent_server_bounded_public_proof(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_WORKER_MODE", "1")
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_WORKER_MODE", "1")
    snapshot = public_snapshot()
    now = datetime(2026, 8, 12, 20, 30, tzinfo=timezone.utc)
    expected_id = build_verification_id(
        PUBLIC_MISSION_ID,
        snapshot["head_hash"],
        public_verification_idempotency_key(PUBLIC_MISSION_ID, now),
    )
    verifier = StubVerifier()
    client = create_app(
        verification_store=verifier,
        public_snapshot=snapshot,
        static_root=web_root,
        clock=lambda: now,
    ).test_client()

    forged = client.post(
        "/internal/tasks/verify-mission",
        headers={"X-CloudTasks-TaskName": "verify-" + "f" * 40},
        json={
            "cycle_id": "another-mission",
            "expected_head_hash": "f" * 64,
            "verification_id": "verify-" + "f" * 40,
        },
    )
    expired_id = build_verification_id(
        PUBLIC_MISSION_ID,
        snapshot["head_hash"],
        public_verification_idempotency_key(PUBLIC_MISSION_ID, now - timedelta(minutes=6)),
    )
    expired = client.post(
        "/internal/tasks/verify-mission",
        headers={"X-CloudTasks-TaskName": expired_id},
        json={
            "cycle_id": PUBLIC_MISSION_ID,
            "expected_head_hash": snapshot["head_hash"],
            "verification_id": expired_id,
        },
    )
    accepted = client.post(
        "/internal/tasks/verify-mission",
        headers={"X-CloudTasks-TaskName": expected_id},
        json={
            "cycle_id": PUBLIC_MISSION_ID,
            "expected_head_hash": snapshot["head_hash"],
            "verification_id": expected_id,
        },
    )

    assert forged.status_code == 400
    assert expired.status_code == 400
    assert accepted.status_code == 200
    assert verifier.calls == [(PUBLIC_MISSION_ID, snapshot["head_hash"], expected_id)]


def test_mutation_routes_reject_oversized_bodies(web_root: Path) -> None:
    client = create_app(StubJournal(), task_queue=StubQueue(), static_root=web_root).test_client()

    response = client.post(
        "/api/missions/mission-001/verifications",
        data=b"x" * (16 * 1024 + 1),
        content_type="application/json",
    )

    assert response.status_code == 413
    assert response.json["error"]["code"] == "request_too_large"


def test_receipt_endpoint_moves_from_pending_to_verified(web_root: Path) -> None:
    receipt_id = "verify-" + "a" * 40
    pending_reader = StubReceiptReader()
    pending_client = create_app(
        StubJournal(),
        verification_reader=pending_reader,
        static_root=web_root,
    ).test_client()
    verified_reader = StubReceiptReader(
        VerificationReceipt(receipt_id, "mission-001", "b" * 64, 6, "2026-08-12T20:30:03Z")
    )
    verified_client = create_app(
        StubJournal(),
        verification_reader=verified_reader,
        static_root=web_root,
    ).test_client()
    path = f"/api/missions/mission-001/verifications/{receipt_id}"

    pending = pending_client.get(path)
    verified = verified_client.get(path)

    assert pending.status_code == 202
    assert pending.json["status"] == "pending"
    assert verified.status_code == 200
    assert verified.json == {
        "cycle_id": "mission-001",
        "entry_count": 6,
            "head_hash": "b" * 64,
            "sealed_at": "2026-08-12T20:30:03Z",
            "status": "verified",
        "verification_id": receipt_id,
    }


def test_receipt_endpoint_rejects_invalid_identity_without_storage_read(
    web_root: Path,
) -> None:
    reader = StubReceiptReader(error=JournalError("verification ID is invalid"))
    client = create_app(
        StubJournal(),
        verification_reader=reader,
        static_root=web_root,
    ).test_client()

    response = client.get("/api/missions/mission-001/verifications/attacker-path")

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_request"


def public_snapshot() -> dict[str, object]:
    path = Path(__file__).resolve().parents[1] / "artifacts" / "public-mission-v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


def live_public_snapshot() -> dict[str, object]:
    path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "public-mission-cloud-20260811-001.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def judge_live_public_snapshot() -> dict[str, object]:
    path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "public-mission-live-89e73407c43d525c4bc19272.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def self_service_public_snapshot() -> dict[str, object]:
    path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / "public-mission-live-fe8a4e9d756508004f9214de.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_mode_serves_only_fixed_redacted_snapshot_without_firestore(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    journal = StubJournal(error=AssertionError("public service must not read Firestore"))
    client = create_app(
        journal,
        public_snapshot=public_snapshot(),
        static_root=web_root,
    ).test_client()

    response = client.get(f"/api/missions/{PUBLIC_MISSION_ID}")
    missing = client.get("/api/missions/other-mission")

    assert response.status_code == 200
    assert response.json["visibility"] == "public_redacted"
    assert response.headers["Cache-Control"] == "public, max-age=60"
    assert "artifact_name" not in response.get_data(as_text=True)
    assert missing.status_code == 404
    assert journal.calls == []


def test_public_mode_serves_allowlisted_live_refusal_without_firestore(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    journal = StubJournal(error=AssertionError("public service must not read Firestore"))
    client = create_app(
        journal,
        public_snapshot=live_public_snapshot(),
        static_root=web_root,
    ).test_client()

    response = client.get(f"/api/missions/{LIVE_PUBLIC_MISSION_ID}")
    missing = client.get("/api/missions/attacker-controlled-mission")

    assert response.status_code == 200
    assert response.json["entries"][-1]["stage"] == "rejected"
    assert response.headers["Cache-Control"] == "public, max-age=60"
    assert "artifact_name" not in response.get_data(as_text=True)
    assert missing.status_code == 404
    assert journal.calls == []


def test_public_mode_serves_judge_live_refusal_without_firestore(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    journal = StubJournal(error=AssertionError("public service must not read Firestore"))
    client = create_app(
        journal,
        public_snapshot=judge_live_public_snapshot(),
        static_root=web_root,
    ).test_client()

    response = client.get(f"/api/missions/{JUDGE_LIVE_MISSION_ID}")

    assert response.status_code == 200
    assert response.json["head_hash"] == "bd859f2e7102e3c592d95400e920a85e3c330bc823f124de18b5adf9c5a5a98e"
    assert response.json["entries"][4]["payload"]["decision"]["failed_invariants"] == ["routine_recall_regressed"]
    assert "artifact_uri" not in response.get_data(as_text=True)
    assert journal.calls == []


def test_public_mode_serves_self_service_case_without_firestore(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    journal = StubJournal(error=AssertionError("public service must not read Firestore"))
    client = create_app(
        journal,
        public_snapshot=self_service_public_snapshot(),
        static_root=web_root,
    ).test_client()

    response = client.get(f"/api/missions/{SELF_SERVICE_PUBLIC_MISSION_ID}")

    assert response.status_code == 200
    assert response.json["head_hash"] == "a738d0dafde538062d63dfbe6b5fd1540a261b303af5a74155397fa9e6d4bd0b"
    assert response.json["entries"][0]["payload"]["evidence_case_count"] == 92
    assert response.json["entries"][4]["payload"]["decision"]["failed_invariants"] == [
        "minimum_target_gain",
        "maximum_regression_drop",
        "minimum_safety_accuracy",
        "require_zero_critical_misses",
    ]
    assert "model_revision" not in response.get_data(as_text=True)
    assert journal.calls == []


def test_public_verification_uses_one_server_controlled_task_identity_per_minute(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    journal = StubJournal(error=AssertionError("public trigger must not read Firestore"))
    queue = StubQueue()
    snapshot = public_snapshot()
    now = datetime(2026, 8, 12, 20, 30, 45, tzinfo=timezone.utc)
    expected_key = public_verification_idempotency_key(PUBLIC_MISSION_ID, now)
    client = create_app(
        journal,
        task_queue=queue,
        public_snapshot=snapshot,
        static_root=web_root,
        clock=lambda: now,
    ).test_client()

    response = client.post(
        f"/api/missions/{PUBLIC_MISSION_ID}/verifications",
        headers={"Idempotency-Key": "attacker:unbounded-key"},
        json={"expected_head_hash": snapshot["head_hash"]},
    )

    assert response.status_code == 202
    assert queue.calls == [(PUBLIC_MISSION_ID, snapshot["head_hash"], expected_key)]
    assert journal.calls == []


def test_public_verification_deduplicates_within_a_minute_and_rotates_afterward(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    snapshot = public_snapshot()
    current = [datetime(2026, 8, 12, 20, 30, 1, tzinfo=timezone.utc)]
    queue = StubQueue()
    client = create_app(
        StubJournal(error=AssertionError("public trigger must not read Firestore")),
        task_queue=queue,
        public_snapshot=snapshot,
        static_root=web_root,
        clock=lambda: current[0],
    ).test_client()
    path = f"/api/missions/{PUBLIC_MISSION_ID}/verifications"
    body = {"expected_head_hash": snapshot["head_hash"]}

    client.post(path, json=body)
    current[0] = current[0].replace(second=59)
    client.post(path, json=body)
    current[0] += timedelta(seconds=1)
    client.post(path, json=body)

    assert queue.calls[0][2] == queue.calls[1][2]
    assert queue.calls[2][2] != queue.calls[1][2]


def test_public_receipt_endpoint_accepts_only_recent_or_legacy_bounded_ids(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    snapshot = public_snapshot()
    now = datetime(2026, 8, 12, 20, 30, tzinfo=timezone.utc)
    expected_id = build_verification_id(
        PUBLIC_MISSION_ID,
        snapshot["head_hash"],
        public_verification_idempotency_key(PUBLIC_MISSION_ID, now - timedelta(minutes=1)),
    )
    reader = StubReceiptReader(
        VerificationReceipt(expected_id, PUBLIC_MISSION_ID, snapshot["head_hash"], 6, "2026-08-12T20:29:03Z")
    )
    client = create_app(
        StubJournal(),
        verification_reader=reader,
        public_snapshot=snapshot,
        static_root=web_root,
        clock=lambda: now,
    ).test_client()

    denied = client.get(
        f"/api/missions/{PUBLIC_MISSION_ID}/verifications/verify-{'f' * 40}"
    )
    accepted = client.get(
        f"/api/missions/{PUBLIC_MISSION_ID}/verifications/{expected_id}"
    )

    assert denied.status_code == 404
    assert accepted.status_code == 200
    assert accepted.json["sealed_at"] == "2026-08-12T20:29:03Z"
    assert reader.calls == [(PUBLIC_MISSION_ID, expected_id)]


def test_public_receipt_fails_closed_when_snapshot_is_invalid(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    snapshot = public_snapshot()
    snapshot["head_hash"] = "f" * 64
    reader = StubReceiptReader()
    client = create_app(
        StubJournal(),
        verification_reader=reader,
        public_snapshot=snapshot,
        static_root=web_root,
    ).test_client()

    response = client.get(
        f"/api/missions/{PUBLIC_MISSION_ID}/verifications/verify-{'a' * 40}"
    )

    assert response.status_code == 503
    assert response.json["error"]["code"] == "evidence_integrity_failure"
    assert reader.calls == []
