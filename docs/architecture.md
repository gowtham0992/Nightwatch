# Nightwatch target architecture

The deployed slice proves the complete retained qualification story and a secure asynchronous verification path. Firestore holds a real six-stage mission built from Gemini/ADK curriculum evidence, Modal training reports, and deterministic policy-v2 evaluation. An IAM-protected Cloud Run control service serves the complete verified chain. A separate public Cloud Run service serves a checked-in redacted projection tied to that chain's exact head; it cannot read Firestore. Cloud Tasks invokes a private worker that re-reads the live chain and creates one immutable receipt object. Cloud-triggered training and a production pointer remain intentionally absent.

## Mission persistence contract

Firestore stores one mission head at `missions/{cycle_id}` and one immutable document per stage at `missions/{cycle_id}/entries/{stage}`. A transaction reads both documents before writing the next entry and updated head. The stage document ID makes retries naturally idempotent; the transaction rejects a replay whose payload differs, a skipped transition, a terminal-stage append, an unsafe mission ID, or a payload larger than 256 KiB. Each mission owns an independent SHA-256 chain beginning at the fixed genesis hash.

The application exposes no direct Firestore writes. The private trigger binds each request to the exact observed head and a validated idempotency key. The public trigger accepts only the retained mission head and replaces caller input with one fixed public idempotency key, so arbitrary requests cannot create unbounded task identities. The public path has its own queue, OIDC invoker, private verifier service, and receipt bucket. Its worker accepts only the exact bundled mission, head, and content-derived receipt ID. Both queues use one concurrent dispatch, one dispatch per second, a 30-second retry window, and private OIDC targets. A worker re-reads the entire chain before creating a generation-zero receipt; it cannot overwrite or delete receipts.

The control service accepts an allowlisted mission ID, verifies at most seven lifecycle entries through the journal contract, and returns either the complete chain or a fail-closed error. It lazily creates Google Cloud clients so its shallow health endpoint does not amplify dependency failures. Both Cloud Run services scale to zero. The control service is capped at two instances; the single-concurrency worker is capped at one.

![Nightwatch target architecture](images/hb3so.png)

## Capability boundaries

| Identity | Can read | Can write | Explicitly denied |
|---|---|---|---|
| `nightwatch-evidence` | Firestore mission evidence | one Cloud Tasks queue | Firestore writes, receipt objects, public invocation |
| `nightwatch-public` | one bundled redacted snapshot; isolated public receipt bucket | one fixed task identity in the isolated public queue | Firestore, private evidence, receipt writes, arbitrary task identities |
| `nightwatch-public-invoker` | nothing | nothing | all access except invoking `nightwatch-public-verifier` |
| `nightwatch-tasks-invoker` | nothing | nothing | all access except invoking `nightwatch-verifier` |
| `nightwatch-worker` | Firestore mission evidence | create-only objects in the private and isolated public receipt buckets | Firestore writes, object reads/overwrite/delete, model execution |
| `nightwatch-diagnostician` | aggregate metrics | diagnosis objects | curriculum and hidden prompts |
| `nightwatch-curriculum` | diagnoses | curriculum bucket | hidden eval bucket and production pointer |
| `nightwatch-trainer` | curriculum bucket, base-model secret | candidate adapter prefix | hidden eval bucket and production pointer |
| `nightwatch-evaluator` | candidate adapters, hidden eval bucket | immutable reports | curriculum bucket and production pointer |
| `nightwatch-promoter` | reports and fixed policy | production pointer, journal | model generation and policy mutation |

The first five rows are deployed identities. The remaining rows describe the target training and promotion split; they are not deployed security boundaries yet. Agent names inside one ADK process are not a security boundary.

## Promotion invariants

The gate promotes only when all conditions hold:

1. Target-suite gain is at least 20 percentage points.
2. Regression-suite accuracy does not decline.
3. Regression `defer` and `investigate` recall each remain at least 50% and do not decline from baseline.
4. No safety-critical case fails.
5. Every frozen case has exactly one valid prediction.
6. Training prompts have no canonical exact overlap with frozen eval prompts.
7. The measured baseline causes the gate to reject all three constant-label policies.

Gemini can diagnose and propose curriculum. It cannot edit thresholds, scores, evaluation labels, journal history, or the production pointer.
