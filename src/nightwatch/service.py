from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Protocol

from flask import Flask, Response, jsonify, request
from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.auth.exceptions import GoogleAuthError

from nightwatch.firestore_journal import FirestoreJournal, validate_cycle_id
from nightwatch.journal import ALLOWED_TRANSITIONS, JournalEntry, JournalError


class JournalReader(Protocol):
    def read_cycle(self, cycle_id: str) -> list[JournalEntry]: ...


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
    static_root: Path | None = None,
) -> Flask:
    web_root = static_root or Path(os.environ.get("NIGHTWATCH_WEB_ROOT", "/app/web-dist"))
    app = Flask(__name__, static_folder=str(web_root), static_url_path="")
    journal = reader
    journal_lock = threading.Lock()

    def get_journal() -> JournalReader:
        nonlocal journal
        if journal is None:
            with journal_lock:
                if journal is None:
                    journal = FirestoreJournal.from_default(
                        project=os.environ.get("GOOGLE_CLOUD_PROJECT")
                    )
        return journal

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
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    @app.get("/api/health")
    def health() -> Response:
        return jsonify(
            {
                "status": "ok",
                "service": "nightwatch-evidence",
                "release": os.environ.get("NIGHTWATCH_RELEASE", "dev"),
            }
        )

    @app.get("/api/missions/<path:cycle_id>")
    def mission(cycle_id: str) -> tuple[Response, int] | Response:
        try:
            validate_cycle_id(cycle_id)
        except JournalError:
            return _error("invalid_cycle_id", "The mission ID is invalid.", 400)
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
        return _error("method_not_allowed", "This endpoint is read-only.", 405)

    @app.get("/")
    def index() -> tuple[Response, int] | Response:
        index_path = web_root / "index.html"
        if not index_path.is_file():
            return _error("ui_unavailable", "The web bundle is unavailable.", 503)
        return app.send_static_file("index.html")

    return app
