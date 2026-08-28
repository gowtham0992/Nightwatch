from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nightwatch.generic_agents import GEMINI_AGENT_MODEL, SPECIALIST_BRIEFS


SPECIALIST_NAMES = ("target_repair", "safety_boundary", "regression_guard")
SPECIALIST_SCHEMA_VERSION = "nightwatch.specialist.v1"
MAX_A2A_REQUEST_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiagnosisPacket(StrictModel):
    headline: str = Field(min_length=12, max_length=160)
    failure_pattern: str = Field(min_length=30, max_length=700)
    evidence_case_ids: list[str] = Field(min_length=1, max_length=8)
    repair_objective: str = Field(min_length=20, max_length=500)
    protected_behaviors: list[str] = Field(min_length=2, max_length=6)


class ObservedError(StrictModel):
    case_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4000)
    expected_label: str = Field(min_length=1, max_length=64)
    predicted_label: str = Field(min_length=1, max_length=64)


class SpecialistRequest(StrictModel):
    schema_version: Literal["nightwatch.specialist.v1"]
    cycle_id: str
    manifest_id: str
    specialist: str
    assignment: str
    diagnosis: DiagnosisPacket
    observed_errors: list[ObservedError] = Field(min_length=1, max_length=32)
    labels: list[str] = Field(min_length=2, max_length=16)
    classification_instruction: str = Field(min_length=10, max_length=4000)

    @field_validator("cycle_id", "manifest_id")
    @classmethod
    def identifier_is_bounded(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("identifier is outside the bounded Nightwatch format")
        return value

    @field_validator("specialist")
    @classmethod
    def specialist_is_registered(cls, value: str) -> str:
        if value not in SPECIALIST_NAMES:
            raise ValueError("specialist is outside the registered Nightwatch taxonomy")
        return value

    @field_validator("labels")
    @classmethod
    def labels_are_unique(cls, value: list[str]) -> list[str]:
        normalized = [label.strip() for label in value]
        if any(not label or len(label) > 64 for label in normalized):
            raise ValueError("labels must be non-empty and at most 64 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("labels must be unique")
        return normalized

    @model_validator(mode="after")
    def request_is_bound_to_assignment_and_evidence(self) -> "SpecialistRequest":
        if self.assignment != SPECIALIST_BRIEFS[self.specialist]:
            raise ValueError("assignment does not match the registered specialist")
        allowed = {row.case_id for row in self.observed_errors}
        if not set(self.diagnosis.evidence_case_ids) <= allowed:
            raise ValueError("diagnosis cites evidence outside the projected packet")
        expected_labels = set(self.labels)
        for row in self.observed_errors:
            if row.expected_label not in expected_labels or row.predicted_label not in expected_labels:
                raise ValueError("observed error contains a label outside the frozen contract")
        return self


class AuthoredExample(StrictModel):
    text: str = Field(min_length=3, max_length=1000)
    label: str = Field(min_length=1, max_length=64)


class SpecialistResponse(StrictModel):
    rationale: str = Field(min_length=20, max_length=400)
    examples: list[AuthoredExample] = Field(min_length=8, max_length=16)


def canonical_json_sha256(value: BaseModel | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json", by_alias=True, exclude_none=True) if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_specialist_request(text: str) -> SpecialistRequest:
    if len(text.encode("utf-8")) > MAX_A2A_REQUEST_BYTES:
        raise ValueError("specialist request exceeds the 64 KiB boundary")
    return SpecialistRequest.model_validate_json(text)


def validate_specialist_response(response: SpecialistResponse, request: SpecialistRequest) -> SpecialistResponse:
    labels = set(request.labels)
    if {example.label for example in response.examples} != labels:
        raise ValueError("specialist response does not cover every frozen label")
    evaluation_prompts = {" ".join(row.text.lower().split()) for row in request.observed_errors}
    seen: set[str] = set()
    for example in response.examples:
        normalized = " ".join(example.text.lower().split())
        if example.label not in labels or normalized in seen or normalized in evaluation_prompts:
            raise ValueError("specialist response violates labels, uniqueness, or leakage policy")
        seen.add(normalized)
    return response


def configured_specialist() -> str:
    specialist = os.environ.get("NIGHTWATCH_SPECIALIST_NAME", "safety_boundary")
    if specialist not in SPECIALIST_NAMES:
        raise RuntimeError("NIGHTWATCH_SPECIALIST_NAME is not registered")
    return specialist


def build_agent(specialist: str | None = None):
    try:
        from google.adk.agents import LlmAgent
    except ImportError as exc:
        raise RuntimeError("Google ADK A2A dependencies are not installed") from exc

    selected = specialist or configured_specialist()
    assignment = SPECIALIST_BRIEFS[selected]
    return LlmAgent(
        name=f"nightwatch_{selected}",
        model=GEMINI_AGENT_MODEL,
        description="Authors bounded safety curriculum for a frozen Nightwatch classifier-repair mission.",
        instruction=(
            f"You are Nightwatch's {selected.replace('_', ' ').title()} specialist. "
            f"Your fixed assignment is: {assignment} The incoming message is a JSON object "
            "validated against the Nightwatch specialist request schema. Use only its projected diagnosis, "
            "observed errors, approved labels, and classification instruction. Create 8 to 16 original "
            "training examples and cover every approved label at least once. Never copy or closely paraphrase evaluation "
            "text. Never introduce labels, URLs, code, actions, policy changes, compute changes, or deployment "
            "instructions. Return only the requested structured response."
        ),
        output_schema=SpecialistResponse,
        output_key=f"{selected}_output",
        include_contents="none",
    )


def build_agent_card(service_url: str, specialist: str | None = None):
    try:
        from a2a.types import AgentCapabilities, AgentCard, AgentSkill, HTTPAuthSecurityScheme, SecurityScheme
    except ImportError as exc:
        raise RuntimeError("A2A SDK dependencies are not installed") from exc

    selected = specialist or configured_specialist()
    display_name = selected.replace("_", " ").title()
    normalized_url = service_url.rstrip("/")
    if not normalized_url.startswith("https://"):
        raise ValueError("NIGHTWATCH_SPECIALIST_URL must be an HTTPS origin")
    return AgentCard(
        name=f"Nightwatch {display_name}",
        description=f"A governed Nightwatch specialist. {SPECIALIST_BRIEFS[selected]}",
        url=normalized_url + "/",
        version="1.0.0",
        protocolVersion="0.3.0",
        preferredTransport="JSONRPC",
        capabilities=AgentCapabilities(streaming=False, pushNotifications=False),
        defaultInputModes=["application/json"],
        defaultOutputModes=["application/json"],
        skills=[
            AgentSkill(
                id=f"nightwatch.{selected}.v1",
                name=f"{display_name} Curriculum",
                description=SPECIALIST_BRIEFS[selected],
                tags=["nightwatch", "classifier-repair", selected, "bounded-curriculum"],
                inputModes=["application/json"],
                outputModes=["application/json"],
            )
        ],
        securitySchemes={
            "google_oidc": SecurityScheme(
                root=HTTPAuthSecurityScheme(
                    scheme="bearer",
                    bearerFormat="Google Cloud Run OIDC",
                    description="A Google-signed identity token whose audience is this private Cloud Run service.",
                )
            )
        },
        security=[{"google_oidc": []}],
    )


async def _validate_request_context(context):
    from a2a.types import TextPart

    if context.message is None or len(context.message.parts) != 1:
        raise ValueError("specialist accepts exactly one JSON text part")
    part = context.message.parts[0].root
    if not isinstance(part, TextPart):
        raise ValueError("specialist accepts JSON text input only")
    request = parse_specialist_request(part.text)
    if request.specialist != configured_specialist():
        raise ValueError("request specialist does not match this deployed service")
    part.text = request.model_dump_json()
    return context


def create_app():
    try:
        from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
        from google.adk.a2a.executor.config import A2aAgentExecutorConfig, ExecuteInterceptor
        from google.adk.a2a.utils.agent_to_a2a import to_a2a
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request
        from starlette.responses import JSONResponse
    except ImportError as exc:
        raise RuntimeError("Google ADK A2A dependencies are not installed") from exc

    service_url = os.environ.get("NIGHTWATCH_SPECIALIST_URL", "")
    specialist = configured_specialist()
    card = build_agent_card(service_url, specialist)
    config = A2aAgentExecutorConfig(execute_interceptors=[ExecuteInterceptor(before_agent=_validate_request_context)])

    def executor_factory(runner):
        return A2aAgentExecutor(runner=runner, config=config)

    app = to_a2a(build_agent(specialist), agent_card=card, agent_executor_factory=executor_factory)

    class RequestLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            content_length = request.headers.get("content-length")
            if request.method == "POST" and content_length is None:
                return JSONResponse({"error": "content_length_required"}, status_code=411)
            if content_length:
                try:
                    if int(content_length) > MAX_A2A_REQUEST_BYTES:
                        return JSONResponse({"error": "request_too_large"}, status_code=413)
                except ValueError:
                    return JSONResponse({"error": "invalid_content_length"}, status_code=400)
            return await call_next(request)

    app.add_middleware(RequestLimitMiddleware)

    async def health(_request):
        return JSONResponse(
            {
                "status": "ok",
                "service": f"nightwatch-specialist-{specialist.replace('_', '-')}",
                "specialist": specialist,
                "schema_version": SPECIALIST_SCHEMA_VERSION,
                "agent_card_sha256": canonical_json_sha256(card),
            }
        )

    app.add_route("/readyz", health, methods=["GET"])
    return app


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Uvicorn is required to serve the A2A specialist") from exc
    port_text = os.environ.get("PORT", "8080")
    if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
        raise RuntimeError("PORT must be an integer from 1 through 65535")
    uvicorn.run(
        "nightwatch.specialist_a2a:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(port_text),
        server_header=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
