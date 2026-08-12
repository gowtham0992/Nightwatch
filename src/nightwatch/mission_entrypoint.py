from __future__ import annotations

import os

from flask import Flask

from nightwatch.mission_service import create_control_app, create_worker_app


def create_app() -> Flask:
    if os.environ.get("NIGHTWATCH_MISSION_WORKER_MODE") == "1":
        return create_worker_app()
    return create_control_app()
