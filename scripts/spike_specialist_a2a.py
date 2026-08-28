from __future__ import annotations

import asyncio
import json
import os

from nightwatch.registry_probe import EXPECTED_CARD_SHA256, SERVICE_URL, build_real_spike_request
from nightwatch.specialist_client import invoke_specialist


async def _run() -> None:
    token = os.environ.pop("NIGHTWATCH_SPECIALIST_ID_TOKEN", "")
    if not token:
        raise SystemExit("NIGHTWATCH_SPECIALIST_ID_TOKEN is required")
    receipt = await invoke_specialist(
        service_url=SERVICE_URL,
        bearer_token=token,
        request=build_real_spike_request(),
        expected_card_sha256=EXPECTED_CARD_SHA256,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_run())
