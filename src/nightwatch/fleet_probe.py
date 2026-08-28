from __future__ import annotations

import asyncio
import json
import os

from nightwatch.adaptive_fleet import discover_delegation_plan, invoke_delegation_plan
from nightwatch.agent_roster import AGENT_TAXONOMY_VERSION, APPROVED_AGENT_ROSTER, MANDATORY_SPECIALISTS, MAX_SPECIALISTS
from nightwatch.operator_contracts import ApprovedAgent, ComputeLimits, DelegationPolicy, FieldMapping, MissionContract, ReleasePolicy
from nightwatch.registry_probe import build_real_spike_request


def probe_contract() -> MissionContract:
    return MissionContract(
        contract_id="contract-a2a-fleet-probe-2026",
        schema_version=2,
        subject="Agent Registry adaptive fleet probe",
        model_id="google/gemma-3-1b-it",
        model_revision="dcc83ea841ab6100d6b47a070329e1ba4cf78752",
        baseline_artifact="scam-v0-de1e6009-2d77e636-c0e947096d",
        dataset_id="dataset-a2a-fleet-probe-2026",
        dataset_sha256="0" * 64,
        mapping=FieldMapping("case_id", "text", "expected_label", "suite", "safety_critical"),
        labels=("block", "caution", "verify", "routine"),
        instruction=(
            "Classify one received message by the safest immediate handling decision. "
            "Return exactly one label: block, caution, verify, or routine."
        ),
        policy=ReleasePolicy(0.15, 0.0, 0.95, True),
        compute=ComputeLimits(8, 3.0, 0.001, 20260813, 1, 20),
        delegation=DelegationPolicy(
            taxonomy_version=AGENT_TAXONOMY_VERSION,
            maximum_specialists=MAX_SPECIALISTS,
            mandatory_specialists=MANDATORY_SPECIALISTS,
            approved_agents=tuple(
                ApprovedAgent(**{**entry, "capabilities": tuple(entry["capabilities"])})
                for entry in APPROVED_AGENT_ROSTER
            ),
        ),
    )


async def _run() -> None:
    request = build_real_spike_request()
    diagnosis = {
        **request.diagnosis.model_dump(mode="json"),
        "required_capabilities": ["target_repair", "safety_boundary"],
    }
    contract = probe_contract()
    plan = await discover_delegation_plan(diagnosis, contract)
    result = await invoke_delegation_plan(
        cycle_id="cycle-a2a-fleet-probe-2026",
        contract=contract,
        diagnosis=diagnosis,
        failure_packet={"errors": [row.model_dump(mode="json") for row in request.observed_errors]},
        delegation_plan=plan,
    )
    print(
        json.dumps(
            {
                "schema_version": "nightwatch.adaptive-fleet-proof.v1",
                "principal": os.environ.get("CLOUD_RUN_JOB", "cloud-run-job"),
                "registry_location": plan["registry_location"],
                "selected_agents": [
                    {
                        "specialist": entry["specialist"],
                        "agent_urn": entry["agent_urn"],
                        "card_sha256": entry["card_sha256"],
                    }
                    for entry in plan["selected_agents"]
                ],
                "receipts": [
                    {
                        "specialist": receipt["specialist"],
                        "request_sha256": receipt["request_sha256"],
                        "response_sha256": receipt["response_sha256"],
                        "authored_rows": len(receipt["response"]["examples"]),
                    }
                    for receipt in result["receipts"]
                ],
            },
            sort_keys=True,
        )
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
