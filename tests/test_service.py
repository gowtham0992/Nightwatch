from __future__ import annotations

from pathlib import Path

import pytest
from google.api_core.exceptions import ServiceUnavailable
from google.auth.exceptions import DefaultCredentialsError

from nightwatch.contracts import Stage
from nightwatch.journal import GENESIS_HASH, JournalEntry, JournalError
from nightwatch.service import create_app


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

    assert response.status_code == 200
    assert response.json["status"] == "ok"
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
        "error": {"code": "method_not_allowed", "message": "This endpoint is read-only."}
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
