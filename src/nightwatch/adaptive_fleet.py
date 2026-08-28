from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from typing import Any
from urllib.parse import urlsplit

from nightwatch.agent_roster import MANDATORY_SPECIALISTS
from nightwatch.generic_agents import SPECIALIST_BRIEFS
from nightwatch.operator_contracts import MissionContract
from nightwatch.specialist_a2a import SPECIALIST_SCHEMA_VERSION, SpecialistRequest, canonical_json_sha256
from nightwatch.specialist_client import invoke_specialist


REGISTRY_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise RuntimeError("registered specialist endpoint is not a private HTTPS origin")
    if parsed.query or parsed.fragment:
        raise RuntimeError("registered specialist endpoint contains unsupported URL material")
    return f"{parsed.scheme}://{parsed.netloc}"


def required_specialists(diagnosis: dict[str, Any], contract: MissionContract) -> tuple[str, ...]:
    if contract.delegation is None:
        raise RuntimeError("adaptive delegation requires a frozen agent roster")
    requested = diagnosis.get("required_capabilities")
    if not isinstance(requested, list) or not requested:
        raise RuntimeError("diagnosis did not emit bounded repair capabilities")
    allowed = {capability for agent in contract.delegation.approved_agents for capability in agent.capabilities}
    if any(not isinstance(item, str) or item not in allowed for item in requested):
        raise RuntimeError("diagnosis requested a capability outside the frozen taxonomy")
    selected = set(requested) | set(MANDATORY_SPECIALISTS)
    if len(selected) > contract.delegation.maximum_specialists:
        raise RuntimeError("diagnosis exceeded the frozen specialist ceiling")
    return tuple(name for name in SPECIALIST_BRIEFS if name in selected)


async def _access_token() -> str:
    import google.auth
    from google.auth.transport.requests import Request as GoogleRequest

    def refresh() -> tuple[str | None, str | None]:
        credentials, project = google.auth.default(scopes=[REGISTRY_SCOPE])
        credentials.refresh(GoogleRequest())
        return credentials.token, project

    token, resolved_project = await asyncio.to_thread(refresh)
    expected_project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if expected_project and resolved_project not in {None, expected_project}:
        raise RuntimeError("worker credentials resolved to the wrong Google Cloud project")
    if not isinstance(token, str) or not token:
        raise RuntimeError("worker credentials did not produce an access token")
    return token


async def discover_delegation_plan(
    diagnosis: dict[str, Any], contract: MissionContract, *, access_token: str | None = None
) -> dict[str, Any]:
    import httpx

    if contract.delegation is None:
        raise RuntimeError("adaptive delegation requires a frozen agent roster")
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "nightwatch-agentic-0992")
    location = os.environ.get("NIGHTWATCH_AGENT_REGISTRY_LOCATION", "us-central1")
    token = access_token or await _access_token()
    required = required_specialists(diagnosis, contract)
    approved = {agent.specialist: agent for agent in contract.delegation.approved_agents}
    endpoint = f"https://agentregistry.googleapis.com/v1/projects/{project}/locations/{location}/agents:search"
    selected: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        for specialist in required:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {token}", "X-Goog-User-Project": project},
                json={"searchString": f"skills.tags:{specialist}"},
            )
            response.raise_for_status()
            agents = response.json().get("agents")
            if not isinstance(agents, list):
                raise RuntimeError("Agent Registry returned a malformed agents collection")
            pin = approved.get(specialist)
            matches = [agent for agent in agents if pin and agent.get("agentId") == pin.agent_urn]
            if len(matches) != 1:
                raise RuntimeError(f"Agent Registry did not resolve one approved {specialist} identity")
            match = matches[0]
            card = match.get("card", {}).get("content")
            if not isinstance(card, dict) or canonical_json_sha256(card) != pin.card_sha256:
                raise RuntimeError(f"Agent Registry returned a substituted {specialist} card")
            if _origin(str(card.get("url", ""))) != pin.endpoint_origin:
                raise RuntimeError(f"Agent Registry returned a substituted {specialist} endpoint")
            selected.append(
                {
                    **asdict(pin),
                    "capabilities": list(pin.capabilities),
                    "registry_resource": match.get("name"),
                }
            )
    return {
        "schema_version": "nightwatch.delegation-plan.v1",
        "taxonomy_version": contract.delegation.taxonomy_version,
        "required_capabilities": list(required),
        "registry_location": f"projects/{project}/locations/{location}",
        "selected_agents": selected,
    }


async def invoke_delegation_plan(
    *,
    cycle_id: str,
    contract: MissionContract,
    diagnosis: dict[str, Any],
    failure_packet: dict[str, Any],
    delegation_plan: dict[str, Any],
) -> dict[str, Any]:
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    selected = delegation_plan.get("selected_agents")
    if not isinstance(selected, list) or not selected:
        raise RuntimeError("sealed delegation plan contains no specialists")
    projected_errors = [
        {
            "case_id": row["case_id"],
            "text": row["text"],
            "expected_label": row["expected_label"],
            "predicted_label": row["predicted_label"],
        }
        for row in failure_packet.get("errors", [])
    ]

    async def invoke(entry: dict[str, Any]) -> dict[str, Any]:
        specialist = entry["specialist"]
        request = SpecialistRequest.model_validate(
            {
                "schema_version": SPECIALIST_SCHEMA_VERSION,
                "cycle_id": cycle_id,
                "manifest_id": contract.contract_id,
                "specialist": specialist,
                "assignment": SPECIALIST_BRIEFS[specialist],
                "diagnosis": {key: value for key, value in diagnosis.items() if key != "required_capabilities"},
                "observed_errors": projected_errors,
                "labels": list(contract.labels),
                "classification_instruction": contract.instruction,
            }
        )

        def identity_token() -> str:
            return id_token.fetch_id_token(GoogleRequest(), entry["endpoint_origin"])

        token = await asyncio.to_thread(identity_token)
        return await invoke_specialist(
            service_url=entry["endpoint_origin"],
            bearer_token=token,
            request=request,
            expected_card_sha256=entry["card_sha256"],
        )

    receipts = await asyncio.gather(*(invoke(entry) for entry in selected))
    batches = [
        {
            "specialist": receipt["specialist"],
            "assignment": SPECIALIST_BRIEFS[receipt["specialist"]],
            **receipt["response"],
            "a2a_receipt": {key: value for key, value in receipt.items() if key != "response"},
        }
        for receipt in receipts
    ]
    return {"batches": batches, "receipts": receipts}
