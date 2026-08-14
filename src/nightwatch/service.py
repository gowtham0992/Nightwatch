from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from flask import Flask, Response, jsonify, request
from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.auth.exceptions import GoogleAuthError

from nightwatch.firestore_journal import FirestoreJournal, validate_cycle_id
from nightwatch.journal import ALLOWED_TRANSITIONS, JournalEntry, JournalError
from nightwatch.public_evidence import (
    PUBLIC_MISSION_ID,
    PUBLIC_MISSION_IDS,
    PUBLIC_VERIFICATION_GRACE_MINUTES,
    load_public_snapshot,
    public_idempotency_key,
    public_verification_idempotency_key,
    validate_public_snapshot,
)
from nightwatch.verification import (
    GCSMissionVerificationStore,
    GCSVerificationReceiptReader,
    VerificationReceipt,
)


class JournalReader(Protocol):
    def read_cycle(self, cycle_id: str) -> list[JournalEntry]: ...


class VerificationQueue(Protocol):
    def enqueue_verification(
        self,
        cycle_id: str,
        head_hash: str,
        idempotency_key: str,
    ) -> Any: ...


class VerificationStore(Protocol):
    def verify(
        self,
        cycle_id: str,
        expected_head_hash: str,
        verification_id: str,
        *,
        timestamp: str | None = None,
    ) -> VerificationReceipt: ...


class VerificationReceiptReader(Protocol):
    def read(
        self,
        cycle_id: str,
        verification_id: str,
    ) -> VerificationReceipt | None: ...


def _entry_json(entry: JournalEntry) -> dict[str, object]:
    return {
        "cycle_id": entry.cycle_id,
        "stage": entry.stage.value,
        "timestamp": entry.timestamp,
        "payload": entry.payload,
        "previous_hash": entry.previous_hash,
        "entry_hash": entry.entry_hash,
    }


def _error(code: str, message: str, status: int) -> tuple[Response, int]:
    return jsonify({"error": {"code": code, "message": message}}), status


def create_app(
    reader: JournalReader | None = None,
    *,
    task_queue: VerificationQueue | None = None,
    verification_store: VerificationStore | None = None,
    verification_reader: VerificationReceiptReader | None = None,
    public_snapshot: dict[str, Any] | None = None,
    static_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Flask:
    web_root = static_root or Path(os.environ.get("NIGHTWATCH_WEB_ROOT", "/app/web-dist"))
    app = Flask(__name__, static_folder=str(web_root), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    public_mode = os.environ.get("NIGHTWATCH_PUBLIC_MODE") == "1"
    journal = reader
    journal_lock = threading.Lock()
    queue = task_queue
    queue_lock = threading.Lock()
    verifier = verification_store
    verifier_lock = threading.Lock()
    receipt_reader = verification_reader
    receipt_reader_lock = threading.Lock()
    redacted_snapshots = (
        {public_snapshot["cycle_id"]: public_snapshot}
        if public_snapshot is not None and isinstance(public_snapshot.get("cycle_id"), str)
        else {}
    )
    redacted_snapshot_lock = threading.Lock()
    now = clock or (lambda: datetime.now(timezone.utc))

    def allowed_public_verification_ids(cycle_id: str, head_hash: str) -> set[str]:
        from nightwatch.cloud_tasks import verification_id as build_verification_id

        current = now()
        ids = {
            build_verification_id(
                cycle_id,
                head_hash,
                public_verification_idempotency_key(
                    cycle_id,
                    current - timedelta(minutes=offset),
                ),
            )
            for offset in range(PUBLIC_VERIFICATION_GRACE_MINUTES + 1)
        }
        # Preserve access to the two receipts created before fresh public proof existed.
        ids.add(build_verification_id(cycle_id, head_hash, public_idempotency_key(cycle_id)))
        return ids

    def get_journal() -> JournalReader:
        nonlocal journal
        if journal is None:
            with journal_lock:
                if journal is None:
                    journal = FirestoreJournal.from_default(
                        project=os.environ.get("GOOGLE_CLOUD_PROJECT")
                    )
        return journal

    def get_task_queue() -> VerificationQueue:
        nonlocal queue
        if queue is None:
            with queue_lock:
                if queue is None:
                    from nightwatch.cloud_tasks import CloudTasksVerificationQueue

                    required = {
                        "project": os.environ.get("GOOGLE_CLOUD_PROJECT"),
                        "location": os.environ.get("NIGHTWATCH_TASKS_LOCATION"),
                        "queue": os.environ.get("NIGHTWATCH_TASKS_QUEUE"),
                        "worker_url": os.environ.get("NIGHTWATCH_WORKER_URL"),
                        "invoker_service_account": os.environ.get(
                            "NIGHTWATCH_TASKS_INVOKER_SERVICE_ACCOUNT"
                        ),
                    }
                    if not all(required.values()):
                        raise RuntimeError("Cloud Tasks verification is not configured")
                    queue = CloudTasksVerificationQueue.from_default(**required)  # type: ignore[arg-type]
        return queue

    def get_verifier() -> VerificationStore:
        nonlocal verifier
        if verifier is None:
            with verifier_lock:
                if verifier is None:
                    bucket_name = os.environ.get("NIGHTWATCH_RECEIPTS_BUCKET")
                    if not bucket_name:
                        raise RuntimeError("verification receipt bucket is not configured")
                    verifier = GCSMissionVerificationStore.from_default(
                        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                        bucket_name=bucket_name,
                    )
        return verifier

    def get_receipt_reader() -> VerificationReceiptReader:
        nonlocal receipt_reader
        if receipt_reader is None:
            with receipt_reader_lock:
                if receipt_reader is None:
                    bucket_name = os.environ.get("NIGHTWATCH_RECEIPTS_BUCKET")
                    if not bucket_name:
                        raise RuntimeError("verification receipt bucket is not configured")
                    receipt_reader = GCSVerificationReceiptReader.from_default(
                        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                        bucket_name=bucket_name,
                    )
        return receipt_reader

    def get_public_snapshot(cycle_id: str = PUBLIC_MISSION_ID) -> dict[str, Any]:
        if cycle_id not in PUBLIC_MISSION_IDS:
            raise JournalError("public mission is not allowlisted")
        with redacted_snapshot_lock:
            snapshot = redacted_snapshots.get(cycle_id)
            if snapshot is None:
                missions_dir = os.environ.get("NIGHTWATCH_PUBLIC_MISSIONS_DIR")
                path = (
                    Path(missions_dir) / f"{cycle_id}.json"
                    if missions_dir
                    else Path(
                        os.environ.get(
                            "NIGHTWATCH_PUBLIC_MISSION_PATH",
                            "/app/public-mission.json",
                        )
                    )
                )
                snapshot = load_public_snapshot(path, expected_cycle_id=cycle_id)
                redacted_snapshots[cycle_id] = snapshot
        return validate_public_snapshot(snapshot, expected_cycle_id=cycle_id)

    @app.after_request
    def secure_response(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        if request.path.startswith("/api/"):
            if (
                public_mode
                and request.method == "GET"
                and request.path.removeprefix("/api/missions/") in PUBLIC_MISSION_IDS
                and response.status_code == 200
            ):
                response.headers["Cache-Control"] = "public, max-age=60"
            else:
                response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    @app.get("/api/health")
    def health() -> Response:
        return jsonify(
            {
                "status": "ok",
                "service": "nightwatch-public" if public_mode else "nightwatch-evidence",
                "release": os.environ.get("NIGHTWATCH_RELEASE", "dev"),
                "visibility": "public_redacted" if public_mode else "private",
            }
        )

    @app.get("/api/missions/<path:cycle_id>")
    def mission(cycle_id: str) -> tuple[Response, int] | Response:
        try:
            validate_cycle_id(cycle_id)
        except JournalError:
            return _error("invalid_cycle_id", "The mission ID is invalid.", 400)
        if public_mode:
            if cycle_id not in PUBLIC_MISSION_IDS:
                return _error("mission_not_found", "No public mission exists with that ID.", 404)
            try:
                return jsonify(get_public_snapshot(cycle_id))
            except JournalError:
                app.logger.exception("public mission snapshot integrity failure")
                return _error(
                    "evidence_integrity_failure",
                    "The public mission evidence failed its integrity check.",
                    503,
                )
        try:
            entries = get_journal().read_cycle(cycle_id)
        except JournalError:
            app.logger.exception("mission evidence integrity failure", extra={"cycle_id": cycle_id})
            return _error(
                "evidence_integrity_failure",
                "The mission evidence failed its integrity check.",
                503,
            )
        except (GoogleAPICallError, GoogleAuthError, RetryError):
            app.logger.exception("mission evidence dependency unavailable", extra={"cycle_id": cycle_id})
            return _error(
                "dependency_unavailable",
                "Mission evidence is temporarily unavailable.",
                503,
            )
        if not entries:
            return _error("mission_not_found", "No verified mission exists with that ID.", 404)
        return jsonify(
            {
                "cycle_id": cycle_id,
                "entry_count": len(entries),
                "head_hash": entries[-1].entry_hash,
                "terminal": not bool(ALLOWED_TRANSITIONS[entries[-1].stage]),
                "entries": [_entry_json(entry) for entry in entries],
            }
        )

    @app.post("/api/missions/<path:cycle_id>/verifications")
    def schedule_verification(cycle_id: str) -> tuple[Response, int] | Response:
        try:
            validate_cycle_id(cycle_id)
        except JournalError:
            return _error("invalid_cycle_id", "The mission ID is invalid.", 400)
        idempotency_key = request.headers.get("Idempotency-Key", "")
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"expected_head_hash"}:
            return _error(
                "invalid_request",
                "Provide exactly one expected_head_hash field.",
                400,
            )
        try:
            if public_mode:
                if cycle_id not in PUBLIC_MISSION_IDS:
                    return _error("mission_not_found", "No public mission exists with that ID.", 404)
                current_head = get_public_snapshot(cycle_id)["head_hash"]
                idempotency_key = public_verification_idempotency_key(cycle_id, now())
            else:
                entries = get_journal().read_cycle(cycle_id)
                if not entries:
                    return _error("mission_not_found", "No verified mission exists with that ID.", 404)
                current_head = entries[-1].entry_hash
            if body["expected_head_hash"] != current_head:
                return _error(
                    "mission_head_changed",
                    "Refresh the mission before requesting verification.",
                    409,
                )
            scheduled = get_task_queue().enqueue_verification(
                cycle_id,
                current_head,
                idempotency_key,
            )
        except JournalError:
            return _error("invalid_request", "The verification request is invalid.", 400)
        except (GoogleAPICallError, GoogleAuthError, RetryError, RuntimeError):
            app.logger.exception("verification queue unavailable", extra={"cycle_id": cycle_id})
            return _error(
                "dependency_unavailable",
                "Mission verification is temporarily unavailable.",
                503,
            )
        response = jsonify(
            {
                "cycle_id": cycle_id,
                "expected_head_hash": current_head,
                "verification_id": scheduled.verification_id,
                "duplicate": scheduled.duplicate,
                "status": "already_accepted" if scheduled.duplicate else "queued",
            }
        )
        response.status_code = 202
        return response

    @app.post("/internal/tasks/verify-mission")
    def verify_mission_task() -> tuple[Response, int] | Response:
        if os.environ.get("NIGHTWATCH_WORKER_MODE") != "1":
            return _error("not_found", "The API route does not exist.", 404)
        task_name = request.headers.get("X-CloudTasks-TaskName", "")
        body = request.get_json(silent=True)
        required = {"cycle_id", "expected_head_hash", "verification_id"}
        if (
            not isinstance(body, dict)
            or set(body) != required
            or task_name.rsplit("/", 1)[-1] != body.get("verification_id")
        ):
            return _error("invalid_task", "The task envelope is invalid.", 400)
        if os.environ.get("NIGHTWATCH_PUBLIC_WORKER_MODE") == "1":
            public_cycle_id = body.get("cycle_id") if isinstance(body, dict) else None
            if public_cycle_id not in PUBLIC_MISSION_IDS:
                return _error("invalid_task", "The task envelope is invalid.", 400)
            try:
                public_head = get_public_snapshot(public_cycle_id)["head_hash"]
                public_verification_ids = allowed_public_verification_ids(
                    public_cycle_id,
                    public_head,
                )
            except JournalError:
                app.logger.exception("public mission snapshot integrity failure")
                return _error(
                    "evidence_integrity_failure",
                    "The public mission evidence failed its integrity check.",
                    503,
                )
            if (
                body.get("expected_head_hash") != public_head
                or body.get("verification_id") not in public_verification_ids
            ):
                return _error("invalid_task", "The task envelope is invalid.", 400)
        try:
            receipt = get_verifier().verify(
                body["cycle_id"],
                body["expected_head_hash"],
                body["verification_id"],
            )
        except JournalError:
            app.logger.exception("mission verification refused")
            return _error(
                "verification_refused",
                "The mission could not be verified against the requested head.",
                409,
            )
        except (GoogleAPICallError, GoogleAuthError, RetryError, RuntimeError):
            app.logger.exception("mission verification dependency unavailable")
            return _error(
                "dependency_unavailable",
                "Mission verification is temporarily unavailable.",
                503,
            )
        return jsonify(
            {
                "status": "verified",
                "cycle_id": receipt.cycle_id,
                "head_hash": receipt.head_hash,
                "verification_id": receipt.verification_id,
            }
        )

    @app.get("/api/missions/<path:cycle_id>/verifications/<verification_id>")
    def verification_receipt(
        cycle_id: str,
        verification_id: str,
    ) -> tuple[Response, int] | Response:
        if public_mode:
            try:
                if cycle_id not in PUBLIC_MISSION_IDS:
                    raise JournalError("public mission is not allowlisted")
                expected_ids = allowed_public_verification_ids(
                    cycle_id,
                    get_public_snapshot(cycle_id)["head_hash"],
                )
            except JournalError:
                app.logger.exception("public mission snapshot integrity failure")
                return _error(
                    "evidence_integrity_failure",
                    "The public mission evidence failed its integrity check.",
                    503,
                )
            if verification_id not in expected_ids:
                return _error("not_found", "The verification receipt does not exist.", 404)
        try:
            receipt = get_receipt_reader().read(cycle_id, verification_id)
        except JournalError:
            return _error("invalid_request", "The verification receipt ID is invalid.", 400)
        except (GoogleAPICallError, GoogleAuthError, RetryError, RuntimeError):
            app.logger.exception("verification receipt unavailable")
            return _error(
                "dependency_unavailable",
                "The verification receipt is temporarily unavailable.",
                503,
            )
        if receipt is None:
            response = jsonify(
                {
                    "status": "pending",
                    "cycle_id": cycle_id,
                    "verification_id": verification_id,
                }
            )
            response.status_code = 202
            return response
        return jsonify(
            {
                "status": "verified",
                "cycle_id": receipt.cycle_id,
                "head_hash": receipt.head_hash,
                "entry_count": receipt.entry_count,
                "sealed_at": receipt.sealed_at,
                "verification_id": receipt.verification_id,
            }
        )

    @app.errorhandler(404)
    def not_found(_error_value: object) -> tuple[Response, int] | Response:
        if request.path.startswith("/api/"):
            return _error("not_found", "The API route does not exist.", 404)
        index = web_root / "index.html"
        if index.is_file():
            return app.send_static_file("index.html")
        return _error("ui_unavailable", "The web bundle is unavailable.", 503)

    @app.errorhandler(405)
    def method_not_allowed(_error_value: object) -> tuple[Response, int]:
        return _error("method_not_allowed", "This method is not allowed.", 405)

    @app.errorhandler(413)
    def request_too_large(_error_value: object) -> tuple[Response, int]:
        return _error("request_too_large", "The request body is too large.", 413)

    @app.get("/")
    def index() -> tuple[Response, int] | Response:
        index_path = web_root / "index.html"
        if not index_path.is_file():
            return _error("ui_unavailable", "The web bundle is unavailable.", 503)
        return app.send_static_file("index.html")

    return app
