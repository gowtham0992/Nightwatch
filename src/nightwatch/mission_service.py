from __future__ import annotations

import os
import threading
from typing import Any, Callable, Protocol

from flask import Flask, Response, jsonify, request
from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.auth.exceptions import GoogleAuthError

from nightwatch.contracts import Stage
from nightwatch.firestore_journal import FirestoreJournal, validate_cycle_id
from nightwatch.journal import JournalError
from nightwatch.mission_orchestrator import (
    MissionJournal,
    MissionStageExecutor,
    advance_mission,
    next_stage,
    resolve_manifest,
)
from nightwatch.mission_tasks import mission_task_id


class MissionQueue(Protocol):
    def enqueue_stage(
        self,
        cycle_id: str,
        manifest_id: str,
        expected_stage: Stage,
    ) -> Any: ...


def _error(code: str, message: str, status: int) -> tuple[Response, int]:
    return jsonify({"error": {"code": code, "message": message}}), status


def _secure_response(response: Response) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


def _configured_queue() -> MissionQueue:
    from nightwatch.mission_tasks import CloudTasksMissionQueue

    required = {
        "project": os.environ.get("GOOGLE_CLOUD_PROJECT"),
        "location": os.environ.get("NIGHTWATCH_MISSION_TASKS_LOCATION"),
        "queue": os.environ.get("NIGHTWATCH_MISSION_TASKS_QUEUE"),
        "worker_url": os.environ.get("NIGHTWATCH_MISSION_WORKER_URL"),
        "invoker_service_account": os.environ.get(
            "NIGHTWATCH_MISSION_TASKS_INVOKER_SERVICE_ACCOUNT"
        ),
    }
    if not all(required.values()):
        raise RuntimeError("mission queue is not configured")
    return CloudTasksMissionQueue.from_default(**required)  # type: ignore[arg-type]


def create_control_app(*, task_queue: MissionQueue | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    queue = task_queue
    queue_lock = threading.Lock()

    def get_queue() -> MissionQueue:
        nonlocal queue
        if queue is None:
            with queue_lock:
                if queue is None:
                    queue = _configured_queue()
        return queue

    app.after_request(_secure_response)

    @app.get("/healthz")
    def health() -> Response:
        return jsonify({"status": "ok", "service": "nightwatch-mission-control"})

    @app.post("/api/missions")
    def start_mission() -> tuple[Response, int] | Response:
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"cycle_id", "manifest_id"}:
            return _error(
                "invalid_request",
                "Provide exactly cycle_id and manifest_id.",
                400,
            )
        try:
            validate_cycle_id(body["cycle_id"])
            resolve_manifest(body["manifest_id"])
            scheduled = get_queue().enqueue_stage(
                body["cycle_id"],
                body["manifest_id"],
                Stage.CREATED,
            )
        except (JournalError, TypeError):
            return _error("invalid_request", "The mission request is not approved.", 400)
        except (GoogleAPICallError, GoogleAuthError, RetryError, RuntimeError):
            app.logger.exception("mission queue unavailable")
            return _error(
                "dependency_unavailable",
                "The mission queue is temporarily unavailable.",
                503,
            )
        response = jsonify(
            {
                "cycle_id": body["cycle_id"],
                "manifest_id": body["manifest_id"],
                "stage": Stage.CREATED.value,
                "status": "already_accepted" if scheduled.duplicate else "queued",
                "task_id": scheduled.task_id,
            }
        )
        response.status_code = 202
        return response

    @app.errorhandler(404)
    def not_found(_error_value: object) -> tuple[Response, int]:
        return _error("not_found", "The API route does not exist.", 404)

    @app.errorhandler(413)
    def request_too_large(_error_value: object) -> tuple[Response, int]:
        return _error("request_too_large", "The request body is too large.", 413)

    return app


def _configured_worker() -> tuple[MissionJournal, MissionStageExecutor, MissionQueue, Callable[[str], Any]]:
    from nightwatch.generic_mission_stages import GenericTextClassificationStageExecutor
    from nightwatch.generic_runtime import GCSRuntimeCallStore, GenericModalRuntime
    from nightwatch.modal_scam_training_stage import ModalScamTrainingCampaign
    from nightwatch.modal_training_stage import GCSModalCallStore, ModalClassifierTrainingStage
    from nightwatch.safety_mission_stages import SafetyQualificationStageExecutor
    from nightwatch.scam_mission_stages import (
        ManifestStageExecutor,
        ScamSafetyStageExecutor,
        retained_verified_curriculum,
        retained_verified_diagnosis,
    )
    from nightwatch.stage_artifacts import GCSStageArtifactStore
    from nightwatch.operator_contracts import GCSOperatorStore, mission_manifest_from_contract, require_contract

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    bucket_name = os.environ.get("NIGHTWATCH_MISSION_ARTIFACTS_BUCKET")
    if not project or not bucket_name:
        raise RuntimeError("mission worker storage is not configured")
    journal = FirestoreJournal.from_default(project=project)
    artifacts = GCSStageArtifactStore.from_default(project=project, bucket_name=bucket_name)
    call_store = GCSModalCallStore.from_default(project=project, bucket_name=bucket_name)
    operator_store = GCSOperatorStore.from_default(project=project, bucket_name=bucket_name)
    training = ModalClassifierTrainingStage(artifacts, call_store)
    scam_training = ModalScamTrainingCampaign(call_store)
    executor = ManifestStageExecutor(
        {
            "incident_triage": SafetyQualificationStageExecutor(
                artifacts, training_stage=training
            ),
            "scam_safety": ScamSafetyStageExecutor(
                artifacts,
                diagnostician=retained_verified_diagnosis,
                curriculum_architect=retained_verified_curriculum,
                training_campaign=scam_training,
            ),
            "scam_safety_live": ScamSafetyStageExecutor(
                artifacts,
                training_campaign=scam_training,
            ),
            "generic_text_classification": GenericTextClassificationStageExecutor(
                artifacts,
                operator_store,
                GenericModalRuntime(
                    GCSRuntimeCallStore.from_default(project=project, bucket_name=bucket_name)
                ),
            ),
        }
    )
    def resolve_worker_manifest(manifest_id: str):
        if manifest_id.startswith("contract-"):
            return mission_manifest_from_contract(require_contract(operator_store, manifest_id))
        return resolve_manifest(manifest_id)
    return (
        journal,
        executor,
        _configured_queue(),
        resolve_worker_manifest,
    )


def create_worker_app(
    *,
    journal: MissionJournal | None = None,
    executor: MissionStageExecutor | None = None,
    task_queue: MissionQueue | None = None,
    manifest_resolver: Callable[[str], Any] | None = None,
) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    dependencies = (
        (journal, executor, task_queue, manifest_resolver or resolve_manifest)
        if journal is not None and executor is not None and task_queue is not None
        else None
    )
    dependency_lock = threading.Lock()

    def get_dependencies() -> tuple[MissionJournal, MissionStageExecutor, MissionQueue, Callable[[str], Any]]:
        nonlocal dependencies
        if dependencies is None:
            with dependency_lock:
                if dependencies is None:
                    dependencies = _configured_worker()
        return dependencies

    app.after_request(_secure_response)

    @app.get("/healthz")
    def health() -> Response:
        return jsonify({"status": "ok", "service": "nightwatch-mission-worker"})

    @app.post("/internal/tasks/advance-mission")
    def advance_task() -> tuple[Response, int] | Response:
        body = request.get_json(silent=True)
        task_name = request.headers.get("X-CloudTasks-TaskName", "")
        if not isinstance(body, dict) or set(body) != {
            "cycle_id",
            "expected_stage",
            "manifest_id",
        }:
            return _error("invalid_task", "The task envelope is invalid.", 400)
        try:
            expected_stage = Stage(body["expected_stage"])
            expected_task_id = mission_task_id(
                body["cycle_id"], body["manifest_id"], expected_stage
            )
        except (JournalError, TypeError, ValueError):
            return _error("invalid_task", "The task envelope is invalid.", 400)
        if task_name.rsplit("/", 1)[-1] != expected_task_id:
            return _error("invalid_task", "The task envelope is invalid.", 400)

        try:
            active_journal, active_executor, queue, resolve_worker_manifest = get_dependencies()
            manifest = resolve_worker_manifest(body["manifest_id"])
            result = advance_mission(
                body["cycle_id"],
                body["manifest_id"],
                journal=active_journal,
                executor=active_executor,
                expected_stage=expected_stage,
                manifest=manifest,
            )
            entries = active_journal.read_cycle(body["cycle_id"])
            following_stage = next_stage(entries)
            scheduled = (
                queue.enqueue_stage(
                    body["cycle_id"], body["manifest_id"], following_stage
                )
                if following_stage is not None
                else None
            )
        except JournalError:
            app.logger.exception(
                "mission stage refused",
                extra={"cycle_id": body.get("cycle_id"), "stage": body.get("expected_stage")},
            )
            return _error("stage_refused", "The mission stage failed its contract.", 409)
        except (GoogleAPICallError, GoogleAuthError, RetryError, RuntimeError, TimeoutError):
            app.logger.exception(
                "mission stage dependency unavailable",
                extra={"cycle_id": body.get("cycle_id"), "stage": body.get("expected_stage")},
            )
            return _error(
                "dependency_unavailable",
                "The mission stage dependency is temporarily unavailable.",
                503,
            )
        return jsonify(
            {
                "cycle_id": result.cycle_id,
                "entry_hash": result.entry_hash,
                "stage": result.stage.value,
                "terminal": result.terminal,
                "next_stage": following_stage.value if following_stage else None,
                "next_task_id": scheduled.task_id if scheduled else None,
            }
        )

    @app.errorhandler(404)
    def not_found(_error_value: object) -> tuple[Response, int]:
        return _error("not_found", "The API route does not exist.", 404)

    @app.errorhandler(413)
    def request_too_large(_error_value: object) -> tuple[Response, int]:
        return _error("request_too_large", "The request body is too large.", 413)

    return app
