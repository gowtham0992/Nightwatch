from __future__ import annotations

import json
from pathlib import Path

import pytest
from google.api_core.exceptions import ServiceUnavailable
from google.auth.exceptions import DefaultCredentialsError

from nightwatch.cloud_tasks import ScheduledVerification
from nightwatch.cloud_tasks import verification_id as build_verification_id
from nightwatch.contracts import Stage
from nightwatch.journal import GENESIS_HASH, JournalEntry, JournalError
from nightwatch.service import create_app
from nightwatch.public_evidence import PUBLIC_IDEMPOTENCY_KEY, PUBLIC_MISSION_ID
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
        VerificationReceipt(receipt_id, "mission-001", "b" * 64, 6)
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


def test_public_verification_uses_fixed_task_identity_without_firestore(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    journal = StubJournal(error=AssertionError("public trigger must not read Firestore"))
    queue = StubQueue()
    snapshot = public_snapshot()
    client = create_app(
        journal,
        task_queue=queue,
        public_snapshot=snapshot,
        static_root=web_root,
    ).test_client()

    response = client.post(
        f"/api/missions/{PUBLIC_MISSION_ID}/verifications",
        headers={"Idempotency-Key": "attacker:unbounded-key"},
        json={"expected_head_hash": snapshot["head_hash"]},
    )

    assert response.status_code == 202
    assert queue.calls == [(PUBLIC_MISSION_ID, snapshot["head_hash"], PUBLIC_IDEMPOTENCY_KEY)]
    assert journal.calls == []


def test_public_receipt_endpoint_is_pinned_to_one_content_derived_id(
    web_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIGHTWATCH_PUBLIC_MODE", "1")
    snapshot = public_snapshot()
    expected_id = build_verification_id(
        PUBLIC_MISSION_ID,
        snapshot["head_hash"],
        PUBLIC_IDEMPOTENCY_KEY,
    )
    reader = StubReceiptReader(
        VerificationReceipt(expected_id, PUBLIC_MISSION_ID, snapshot["head_hash"], 6)
    )
    client = create_app(
        StubJournal(),
        verification_reader=reader,
        public_snapshot=snapshot,
        static_root=web_root,
    ).test_client()

    denied = client.get(
        f"/api/missions/{PUBLIC_MISSION_ID}/verifications/verify-{'f' * 40}"
    )
    accepted = client.get(
        f"/api/missions/{PUBLIC_MISSION_ID}/verifications/{expected_id}"
    )

    assert denied.status_code == 404
    assert accepted.status_code == 200
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
