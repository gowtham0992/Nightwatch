# Bounded mission orchestrator

Nightwatch's Taskmaster path is one operator-started, autonomous qualification mission. The private release accepts a narrowly bounded, content-addressed contract: a registered Gemma adapter, its pinned revision, canonical CSV/JSONL evidence, explicit field mappings, a versioned gate policy, an approved compute grid, and an exact allowlist of specialist URNs, Agent Card hashes, HTTPS origins, service accounts, and capabilities. It accepts no arbitrary model, agent, URL, storage URI, runtime, code, or deployment target.

Both paths are deployed: the public proof remains a fixed, redacted case study, while the authenticated product completed a real self-service run from upload and baseline discovery through Agent Registry selection, private A2A delegation, bounded training, and deterministic refusal.

## Invariants

- One Cloud Task advances one durable lifecycle stage and then exits.
- A stage is appended only after its evidence artifact exists immutably.
- Agent Registry discovery is treated as untrusted input. Deterministic code intersects diagnosis-required capabilities with the frozen roster and persists the resulting plan before any A2A call.
- Retrying `diagnosed` reads the sealed plan and cannot rediscover a different fleet.
- Every external effect is keyed by cycle ID and stage. Retrying a task loads the existing artifact instead of invoking Gemini or Modal again.
- Gemini may diagnose and design curriculum. It cannot change the manifest, policy, budget, terminal verdict, or deployment state.
- Deterministic policy selects `qualified` or `refused`. The historical journal enum remains `promoted` until a versioned evidence migration, but all judge-facing copy says `qualified`.
- Qualification never mutates a production pointer.
- The public service remains read-only and receives no Firestore, Gemini, Modal, or mission-start permissions.

## Stage contract

| Stage | Real work | Durable proof before append |
|---|---|---|
| created | Fixed proof: resolve its approved manifest. Dynamic mission: run the registered baseline on the frozen dataset and require a real observed failure | Contract identity, baseline predictions, deterministic scores, and failure packet |
| diagnosed | Gemini 3.6 Flash analyzes the baseline failure; deterministic routing resolves required capabilities through Agent Registry | Create-only diagnosis plus sealed delegation plan |
| curriculum_ready | Separate private ADK specialists receive projected evidence over authenticated A2A; deterministic code validates identity, card hash, schema, labels, uniqueness, and leakage | Three create-only specialist artifacts, A2A receipts, and merged curriculum evidence |
| trained | Launch the pinned Modal function once and retrieve its result | Modal call ID plus immutable report and prediction artifacts |
| evaluated | Run frozen evidence through policy v2 | Evaluation report with boolean `accepted` produced by deterministic code |
| promoted/rejected | Record `qualified` or `refused` | Terminal journal entry, followed by the existing verification receipt |

## Failure behavior

- Duplicate task delivery: the stage executor returns the existing content-addressed artifact; Firestore's transaction returns the existing identical journal entry.
- Crash before artifact creation: Cloud Tasks retries and the stage starts again; no durable effect exists yet.
- Crash after artifact creation but before journal append: the retry loads the existing artifact and appends it once.
- Gemini schema or leakage failure: the stage fails loudly and remains resumable; policy is not weakened.
- Missing Registry match, changed card hash, substituted endpoint, or unapproved capability: fail before specialist invocation.
- Modal timeout: persist the function-call ID, poll it from a later task, and never launch a replacement under the same cycle.
- Budget or manifest mismatch: fail closed before any external call.
- Terminal retry: return the existing terminal head without invoking another stage.

## Adaptive-fleet deployed acceptance — August 28, 2026 UTC

- Frozen contract: `contract-8d1d1940d6190b2b50ef7dd8`, containing the pinned Gemma revision, 92-case dataset digest, four release thresholds, one-attempt/20-GPU-minute limits, and the exact three-agent roster.
- Mission: `nightwatch-live-ac7c9d317783b6af4e543b1d`, six entries from `2026-08-28T02:27:57Z` through `2026-08-28T02:29:02Z`, terminal head `6d7d4c0ae6374a6b0230a342a3b0caff44c3fc2586f33173744ac2df2250329f`.
- Discovery: Gemini 3.6 Flash required `target_repair`, `safety_boundary`, and `regression_guard`; read-only Agent Registry search resolved the three frozen Agent Cards, and the plan was sealed before delegation.
- A2A work: three private OIDC-authenticated Cloud Run specialists returned 12, 8, and 10 validated rows. The journal retains distinct Agent Card, request, response, and artifact hashes for each handoff.
- Training: one Modal call, 30 examples, 3.9603 measured runtime seconds, no second attempt.
- Result: target 83.3% → 91.7%, safety 95.8% → 62.5%, regression 78.1% → 68.8%, three critical misses; all four invariants failed and the candidate ended `refused_not_deployed`.
- Recovery evidence: the first baseline call failed closed because Modal still had the v1 contract parser. Its call record and exhausted Cloud Task remain immutable. Runtime generation `g3` and task generation `g2` resumed the same cycle and contract; no second mission, contract, dataset, policy, Gemini diagnosis, or training attempt was created.

## Earlier self-service acceptance

- Authenticated control: `nightwatch-evidence-selfservice-2b`, digest `sha256:addcc8e3c5f28544403bce46950d0ae3aafac671780cef3ba21b14d05b9e3a2f`.
- Private worker: `nightwatch-mission-worker-selfservice-4`, digest `sha256:8fcc5df8eb98bdd8d3881ed0b5aceac344f044547ec21c9879dd4c8a786837c9`, maximum one instance and one concurrent request.
- Self-service mission: `nightwatch-live-fe8a4e9d756508004f9214de`, six stages, terminal head `a738d0dafde538062d63dfbe6b5fd1540a261b303af5a74155397fa9e6d4bd0b`.
- Public case: **Self-service run**, revision `nightwatch-public-selfservice-case2`, redacted projection verified through receipt `verify-a775cde912b516ceac9d501c5717dc59925f1ff6`.
- Real result: refused; target accuracy 83.3% → 72.2%, regression 78.1% → 65.6%, safety 95.8% → 45.8%, seven critical misses, and no deployment.
- Real agent work: Gemini 3.6 Flash diagnosis plus three parallel Google ADK curriculum specialists; 32 authored rows passed deterministic validation.
- Real training: one create-only Modal candidate call, 5.5246 measured training seconds, below the frozen 20-GPU-minute ceiling.
- Recovery evidence: failed external call records remain immutable; generation `g2` is explicit, the same cycle resumed after fail-closed packaging and identity-boundary corrections, and no second mission was created.

### Earlier fixed-manifest acceptance

- Private control: `nightwatch-mission-control` on Cloud Run.
- Private worker: `nightwatch-mission-worker` on Cloud Run, maximum one instance and one concurrent request.
- Immutable container: `sha256:7034d7279a0396e10d0d9aaebee4798e042641cc0fb39384a42c46fbfbc0d77f`.
- Queue: `nightwatch-missions` in `us-central1`, one concurrent dispatch and three bounded attempts.
- Artifact store: private, public-access-prevention-enforced `gs://nightwatch-agentic-0992-mission-artifacts`.
- Fresh unattended mission: `nightwatch-cloud-20260811-001`, six stages from `2026-08-12T00:58:16Z` through `2026-08-12T01:00:01Z`.
- Terminal result: refused; safety met 90%, but regression accuracy was 73.75% and defer recall was 60%.
- Verified terminal head: `b75997fa00e6263d1e5139d1047ea04eef02ab25c4f0f12188cadf7ed1154a85`.
- Create-only receipt: `verify-ae7b0bc76f9623af88ee36746af149ed7fc6f179`.

## Verifiable slices

1. **State-machine contract:** one invocation advances one stage; allowlist/content-address validation, terminal no-op, manifest binding, and both terminal branches are tested locally.
2. **Immutable stage artifacts:** add the create-only GCS stage store and prove retry-after-write returns byte-identical evidence.
3. **Real curriculum stage:** execute Gemini + ADK through the artifact store and append a live `curriculum_ready` entry.
4. **Real training stage:** deploy the existing Modal classifier function, spawn it once, persist its call ID, retrieve its result on a later task, and append `trained`.
5. **Real evaluation and terminal stage:** deterministic policy v2 refused the fresh candidate and a separate verification worker sealed the exact terminal head.
6. **Deployed acceptance:** one authenticated POST created the fresh cycle; no further operator action occurred; honest timestamps span the actual run. Its redacted Registry/A2A proof is the default judge case beside the retained qualification.

## Non-goals

No arbitrary models, arbitrary files, remote dataset URLs, user code, public mission trigger, multi-tenancy, scheduler, Cloud Run GPU migration, production deployment, rollback automation, or chat UI enter this slice. Uploads are data-only and become immutable before a mission can launch.
