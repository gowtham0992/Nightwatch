from __future__ import annotations

from typing import Any


AGENT_TAXONOMY_VERSION = "nightwatch.repair-capabilities.v1"
MAX_SPECIALISTS = 3
MANDATORY_SPECIALISTS = ("regression_guard",)

# This is the operator-approved fleet, not a discovery result. Agent Registry may
# advertise other agents; they remain ineligible unless a new contract version
# explicitly pins their identity, endpoint, service account, and card digest.
APPROVED_AGENT_ROSTER: tuple[dict[str, Any], ...] = (
    {
        "specialist": "target_repair",
        "agent_urn": (
            "urn:agent:projects-1062292041254:projects:1062292041254:locations:us-central1:"
            "agentregistry:services:nightwatch-target-repair"
        ),
        "card_sha256": "036cad8c6dfa975a8e226221aaaf3dc3d2fb804345d372414f14fe589f0f7c9f",
        "endpoint_origin": "https://nightwatch-specialist-target-1062292041254.us-central1.run.app",
        "service_account": "nw-specialist-target@nightwatch-agentic-0992.iam.gserviceaccount.com",
        "capabilities": ("target_repair",),
    },
    {
        "specialist": "safety_boundary",
        "agent_urn": (
            "urn:agent:projects-1062292041254:projects:1062292041254:locations:us-central1:"
            "agentregistry:services:nightwatch-safety-boundary"
        ),
        "card_sha256": "041c574607dfa0f96c039346b43b118e67bffe1767f32862e79388227d76a947",
        "endpoint_origin": "https://nightwatch-specialist-safety-1062292041254.us-central1.run.app",
        "service_account": "nightwatch-specialist-safety@nightwatch-agentic-0992.iam.gserviceaccount.com",
        "capabilities": ("safety_boundary",),
    },
    {
        "specialist": "regression_guard",
        "agent_urn": (
            "urn:agent:projects-1062292041254:projects:1062292041254:locations:us-central1:"
            "agentregistry:services:nightwatch-regression-guard"
        ),
        "card_sha256": "ce023a7c84c4882fbd271f19fe2983013cb712fb85cadcafb5344327b5031a32",
        "endpoint_origin": "https://nightwatch-specialist-regression-1062292041254.us-central1.run.app",
        "service_account": "nw-specialist-regression@nightwatch-agentic-0992.iam.gserviceaccount.com",
        "capabilities": ("regression_guard",),
    },
)


def public_roster() -> list[dict[str, Any]]:
    return [
        {
            **entry,
            "capabilities": list(entry["capabilities"]),
        }
        for entry in APPROVED_AGENT_ROSTER
    ]
