from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from nightwatch.specialist_a2a import (
    SpecialistRequest,
    SpecialistResponse,
    canonical_json_sha256,
    validate_specialist_response,
)


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("specialist endpoint must be an HTTPS origin without user information")
    if parsed.query or parsed.fragment:
        raise ValueError("specialist endpoint must not contain a query or fragment")
    return f"{parsed.scheme}://{parsed.netloc}"


def _extract_text(result: Any) -> str:
    from a2a.types import Message, Task, TextPart

    candidate = result[0] if isinstance(result, tuple) else result
    parts = []
    if isinstance(candidate, Message):
        parts = candidate.parts
    elif isinstance(candidate, Task):
        if not candidate.artifacts:
            raise RuntimeError("A2A specialist returned no completed artifact")
        parts = [part for artifact in candidate.artifacts for part in artifact.parts]
    else:
        raise RuntimeError("A2A specialist returned an unsupported result type")
    texts = [part.root.text for part in parts if isinstance(part.root, TextPart)]
    if len(texts) != 1:
        raise RuntimeError("A2A specialist must return exactly one JSON text artifact")
    return texts[0]


async def invoke_specialist(
    *,
    service_url: str,
    bearer_token: str,
    request: SpecialistRequest,
    expected_card_sha256: str,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    try:
        import httpx
        from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
        from a2a.types import Message, Part, Role, TextPart
    except ImportError as exc:
        raise RuntimeError("A2A client dependencies are not installed") from exc

    base_url = _origin(service_url)
    headers = {"Authorization": f"Bearer {bearer_token}"}
    timeout = httpx.Timeout(timeout_seconds)
    async with httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=False) as http_client:
        card = await A2ACardResolver(http_client, base_url).get_agent_card()
        card_sha256 = canonical_json_sha256(card)
        if card_sha256 != expected_card_sha256:
            raise RuntimeError("registered specialist card hash does not match the frozen contract")
        if _origin(card.url) != base_url:
            raise RuntimeError("registered specialist card changed endpoint origin")
        client = ClientFactory(
            ClientConfig(streaming=False, polling=False, httpx_client=http_client)
        ).create(card)
        message = Message(
            messageId=str(uuid4()),
            role=Role.user,
            parts=[Part(root=TextPart(text=request.model_dump_json()))],
            metadata={
                "nightwatch_cycle_id": request.cycle_id,
                "nightwatch_manifest_id": request.manifest_id,
                "nightwatch_request_sha256": canonical_json_sha256(request),
            },
        )
        results = [result async for result in client.send_message(message)]
        if len(results) != 1:
            raise RuntimeError("non-streaming specialist returned an unexpected event count")
        response_text = _extract_text(results[0])
        response = validate_specialist_response(
            SpecialistResponse.model_validate_json(response_text), request
        )
        return {
            "schema_version": "nightwatch.specialist-receipt.v1",
            "specialist": request.specialist,
            "endpoint_origin": base_url,
            "agent_card_sha256": card_sha256,
            "request_sha256": canonical_json_sha256(request),
            "response_sha256": canonical_json_sha256(response),
            "response": response.model_dump(mode="json"),
        }
