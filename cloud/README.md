# Google Cloud deployment assets

Nightwatch’s production path uses Google Cloud for the control plane, durable orchestration, agent discovery, private A2A execution, evidence, and public proof. Model training is deliberately isolated on Modal behind a one-attempt, cycle-bound claim; no Cloud Run GPU job is part of the submitted deployment.

## Deployed topology

- **Cloud Run:** public judge surface, IAM-protected operator surface, OIDC-only mission worker, isolated verifier, and three private specialist services.
- **Cloud Tasks:** one queue advances bounded mission stages; a separate queue performs public verification.
- **Firestore:** append-only mission journals and terminal heads.
- **Cloud Storage:** create-only artifacts, external-call claims, follow-up proposals and approvals, and isolated verification receipts.
- **Vertex AI + Google ADK:** Gemini 3.6 Flash diagnosis and specialist work.
- **Agent Registry + A2A:** read-only capability discovery followed by contract-pinned, OIDC-authenticated specialist calls.

The authoritative resource inventory, immutable revisions, IAM boundaries, rollout checks, and rollback targets are in [DEPLOYMENT.md](DEPLOYMENT.md).

## Build definitions

| File | Purpose |
|---|---|
| `service-build.yaml` | Shared public and authenticated service image |
| `mission-build.yaml` | Private mission-worker image |
| `specialist-build.yaml` | Private A2A specialist image |
| `agent-registry/` | Checked-in Agent Cards used to register the exact approved specialists |
| `mission-artifacts-lifecycle.json` | Retention policy for private mission artifacts |
| `public-receipts-lifecycle.json` | Retention policy for isolated public-proof receipts |

## Safety requirements

Use separate runtime identities. The public service must have no Firestore, Vertex AI, Agent Registry, specialist-invocation, Modal, or mission-launch permission. The mission worker may read Registry entries but cannot register agents. Each specialist may invoke Vertex AI and nothing else. No application identity receives deployment authority.

Refused dynamic missions automatically seal a create-only follow-up proposal. Only the IAM-protected operator service can approve one child contract, and only after a different canonical evidence SHA and a new capped budget are supplied. The public image contains only the redacted proposal and exposes no approval route.

Deploy with minimum instances set to zero, preserve the documented instance and queue caps, and use immutable image digests. Run the zero-traffic checks and rollback rehearsal in [DEPLOYMENT.md](DEPLOYMENT.md) before moving canonical traffic.
