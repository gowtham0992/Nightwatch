# Bounded mission orchestrator

Nightwatch's deployed Taskmaster path is one operator-started, unattended qualification mission. The operator selects only the approved `safety-270m-v1` manifest; they cannot supply a model ID, revision, dataset path, hyperparameters, budget, storage URI, or deployment target.

## Invariants

- One Cloud Task advances one durable lifecycle stage and then exits.
- A stage is appended only after its evidence artifact exists immutably.
- Every external effect is keyed by cycle ID and stage. Retrying a task loads the existing artifact instead of invoking Gemini or Modal again.
- Gemini may diagnose and design curriculum. It cannot change the manifest, policy, budget, terminal verdict, or deployment state.
- Deterministic policy selects `qualified` or `refused`. The historical journal enum remains `promoted` until a versioned evidence migration, but all judge-facing copy says `qualified`.
- Qualification never mutates a production pointer.
- The public service remains read-only and receives no Firestore, Gemini, Modal, or mission-start permissions.

## Stage contract

| Stage | Real work | Durable proof before append |
|---|---|---|
| created | Resolve the approved manifest and freeze limits | Manifest fields in the journal entry |
| diagnosed | Analyze the fixed baseline failure | Create-only diagnosis JSON |
| curriculum_ready | Gemini 3.6 Flash + ADK generate the bounded intervention; deterministic code validates schema and leakage | Create-only curriculum and evidence JSON |
| trained | Launch the pinned Modal function once and retrieve its result | Modal call ID plus immutable report and prediction artifacts |
| evaluated | Run frozen evidence through policy v2 | Evaluation report with boolean `accepted` produced by deterministic code |
| promoted/rejected | Record `qualified` or `refused` | Terminal journal entry, followed by the existing verification receipt |

## Failure behavior

- Duplicate task delivery: the stage executor returns the existing content-addressed artifact; Firestore's transaction returns the existing identical journal entry.
- Crash before artifact creation: Cloud Tasks retries and the stage starts again; no durable effect exists yet.
- Crash after artifact creation but before journal append: the retry loads the existing artifact and appends it once.
- Gemini schema or leakage failure: the stage fails loudly and remains resumable; policy is not weakened.
- Modal timeout: persist the function-call ID, poll it from a later task, and never launch a replacement under the same cycle.
- Budget or manifest mismatch: fail closed before any external call.
- Terminal retry: return the existing terminal head without invoking another stage.

## Deployed acceptance

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

1. **State-machine contract:** one invocation advances one stage; allowlist, terminal no-op, manifest binding, and both terminal branches are tested locally.
2. **Immutable stage artifacts:** add the create-only GCS stage store and prove retry-after-write returns byte-identical evidence.
3. **Real curriculum stage:** execute Gemini + ADK through the artifact store and append a live `curriculum_ready` entry.
4. **Real training stage:** deploy the existing Modal classifier function, spawn it once, persist its call ID, retrieve its result on a later task, and append `trained`.
5. **Real evaluation and terminal stage:** deterministic policy v2 refused the fresh candidate and a separate verification worker sealed the exact terminal head.
6. **Deployed acceptance:** one authenticated POST created the fresh cycle; no further operator action occurred; honest timestamps span the actual run. Exposing its redacted view alongside the retained qualification is the remaining presentation step.

## Non-goals

No arbitrary models, user uploads, public mission trigger, multi-tenancy, scheduler, Cloud Run GPU migration, production deployment, rollback automation, chat UI, or additional agents enter this slice.
