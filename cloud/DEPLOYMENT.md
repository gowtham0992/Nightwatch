# Deployment runbook

Nightwatch separates its private operator surface, public judge surface, and private verifier in `nightwatch-agentic-0992`.

## Deployed resources

- `nightwatch-evidence`: control API and UI, Firestore read-only, maximum two instances.
- `nightwatch-public`: public redacted UI/API, no Firestore permission, maximum one instance.
- `nightwatch-public-verifier`: private fixed-proof worker, existing Firestore read-only worker identity, maximum one instance and one concurrent request.
- `nightwatch-verifier`: Cloud Tasks worker, Firestore read-only, maximum one instance and one concurrent request.
- `nightwatch-mission-control`: private operator trigger with enqueue-only access, maximum one instance.
- `nightwatch-mission-worker`: private Gemini/ADK + Modal stage worker, maximum one instance and one concurrent request.
- `nightwatch-missions`: one dispatch per second, one concurrent stage, and three bounded attempts.
- `nightwatch-public-verifications`: isolated public queue with the same one-per-second, one-concurrent, 30-second retry limits.
- `nightwatch-verifications`: one dispatch per second, one concurrent dispatch, three configured attempts within a 30-second retry window.
- `nightwatch-agentic-0992-public-verification-receipts`: isolated public-proof bucket with public access prevention and seven-day deletion.
- `nightwatch-agentic-0992-verification-receipts`: uniform bucket-level access, public access prevention, seven-day retention.
- `nightwatch-agentic-0992-mission-artifacts`: regional create-only mission artifacts and external-call claims, public access prevention, 30-day lifecycle.
- `nightwatch-tasks-invoker`: OIDC identity whose only application permission is invoking `nightwatch-verifier`.
- `nightwatch-missions-invoker`: OIDC identity whose only application permission is invoking `nightwatch-mission-worker`.

The canonical private control URL is `https://nightwatch-evidence-w3a6oefsma-uc.a.run.app`. Use the canonical `*.a.run.app` worker URL as both the Cloud Tasks target and OIDC audience; the alternate numeric hostname is not interchangeable for this purpose.

The canonical public judge URL is `https://nightwatch-public-w3a6oefsma-uc.a.run.app`. Public release `b9ef1b9` runs revision `nightwatch-public-gate-b9ef1b9` from immutable image digest `sha256:3e91c394c575ebe4d479d8d86caacb77586303cd5ddcaf9f6920cad1507efef2`. Private release `fc8a7f9` runs revision `nightwatch-evidence-normalize-fc8a7f9` from immutable image digest `sha256:a940e058fc91fae269ecd7032339cfb18d6d8c80a0b324850696713499ca580b`. Verifier revision `nightwatch-public-verifier-judge-a9dbac3` remains on the compatible `a9dbac3` service image. The judge view defaults to the strongest live refusal mission and exposes only its bundled, strictly redacted evidence.

The mission control and worker run immutable image digest `sha256:e3d09ce4d07c652c777034ca5c1c06c217d5862f09c87edbee9cbbe235665478` in revisions `nightwatch-mission-control-scam-ff4f` and `nightwatch-mission-worker-scam-ff4f`. Fresh scam mission `nightwatch-scam-20260814-001` traversed all six stages unattended in 94 seconds and qualified a new cycle-bound adapter. Its terminal Firestore head is `3e7ff1420b51b9accfe4bd325c4faf00d89823d1db2bcbcac08eda6b0a916930`; private receipt `verify-1b69f5647d8003263b96eb03f185b9f653966d3a` independently sealed all six entries. The candidate reached 36/36 target, 24/24 safety, and 28/32 regression cases with zero critical misses and zero benign blocks. It remains qualified, not deployed.

The rollback drill was exercised after the mission completed: traffic returned to `nightwatch-mission-control-00001-4cj` and `nightwatch-mission-worker-00002-s58`, then restored to the new revisions with no queued work and no ERROR-level release logs.

## Mission Control release — August 14, 2026

Commit `c5916d6` is deployed on private revision `nightwatch-evidence-ui-c5916d6` and public revision `nightwatch-public-ui-c5916d6` from service image digest `sha256:afed24b5322fe1a5ed88b8200c4338648c6819667369ea076e6247d502810a27`. The live-agent worker remains commit `cdcbf25`, revision `nightwatch-mission-worker-mc-cdcbf25`, image digest `sha256:406670e7d948f52e89a725bb6d45ec70e40bcaddba8b7d1ea1d1f8f93cddeee9`. The public health contract reports `operator_enabled: false`, and the public operator route returns 404.

Two independently triggered live-agent cycles completed end to end. `nightwatch-live-5d3321c672472c5a381404c5` was refused because safety-block recall was 94.4% against the fixed 95% floor, despite improving target accuracy from 63.9% to 94.4%. `nightwatch-live-89e73407c43d525c4bc19272` reached 100% target and 100% safety but was refused because routine-message recall fell by 12.5 percentage points. Both used live Gemini 3.6 Flash diagnosis and parallel ADK curriculum authors, one create-only Modal training call, deterministic evaluation, six hash-chained Firestore entries, and `refused_not_deployed` as the terminal state. The queue was confirmed empty afterward and worker ERROR logs were empty.

Rollback was exercised against the live environment before the missions: worker traffic returned to `nightwatch-mission-worker-scam-ff4f`, private traffic to `nightwatch-evidence-00005-fds`, and public traffic to `nightwatch-public-scam-e481-v2`; all three were then restored to the new revisions. The mission queue was paused briefly while an unexpected second operator cycle was audited, then resumed after both cycles were terminal and confirmed empty.

## Judge story release — August 14, 2026

Commit `a9dbac3` is deployed to the public, private, and public-proof verifier services from the same immutable image digest. The default judge mission is `nightwatch-live-89e73407c43d525c4bc19272`, with six hash-chained entries and terminal head `bd859f2e7102e3c592d95400e920a85e3c330bc823f124de18b5adf9c5a5a98e`. It improved target accuracy from 63.9% to 100.0% and safety accuracy from 95.8% to 100.0%, but the deterministic gate refused release because routine-message recall regressed from 87.5% to 75.0%. The qualified scam-repair mission remains available as the second case file rather than being presented as the default story.

The production proof path was exercised after promotion. Public verification `verify-11ad0d4091590155d014cfd346fb9c1e9338963a` was queued through Cloud Tasks, independently reread by the private verifier, and sealed all six entries at the exact terminal head. The public operator route remained 404. No training or model endpoint was invoked during this release verification.

That receipt ID is a historical deployment record, not a permanent public capability. The public API accepts the fixed legacy proof identity plus server-derived identities from the current and previous five UTC minutes; older minute-bound IDs deliberately return 404 even while their create-only Cloud Storage objects remain governed by the bucket lifecycle. The judge UI requests a fresh server-derived identity and polls it immediately. A 404 for the historical ID therefore does not mean the recorded verification failed, and the documentation does not present it as a durable public URL.

Known-good rollback targets are `nightwatch-public-ui-c5916d6`, `nightwatch-evidence-ui-c5916d6`, and `nightwatch-public-verifier-00003-mgn`. The live mission worker remains unchanged on `nightwatch-mission-worker-mc-cdcbf25`.

UI follow-up `b9ef1b9` separates execution completion from gate outcome: completed upstream agents retain green checks, while a rejected gate renders a red blocked mark and `REFUSED`; its inspector states `evaluation complete`. The public and authenticated private zero-traffic candidates were exercised against the real refusal mission with clean browser consoles before promotion. The private candidate also confirmed that operator mode and the real launch control remained enabled without launching a mission. `nightwatch-public-judge-a9dbac3-r2` and `nightwatch-evidence-judge-a9dbac3-r2` are the immediate rollback targets.

Private follow-up `fc8a7f9` normalizes the raw private journal's `decision.reasons` and `critical_misses` array into the same release-gate facts exposed by the redacted public evidence. Its zero-traffic candidate was rehearsed across the real refusal case, qualified case, browser back-navigation, and enabled operator control without launching a mission. The refusal inspector showed `Routine-message recall regressed` and zero critical misses; the browser console remained clean. `nightwatch-evidence-gate-b9ef1b9` is the immediate private rollback target.

## Self-service mission release — August 20, 2026

The authenticated control surface runs revision `nightwatch-evidence-selfservice-2b` from immutable image digest `sha256:addcc8e3c5f28544403bce46950d0ae3aafac671780cef3ba21b14d05b9e3a2f`. The private stage worker runs revision `nightwatch-mission-worker-selfservice-4` from digest `sha256:8fcc5df8eb98bdd8d3881ed0b5aceac344f044547ec21c9879dd4c8a786837c9`. The isolated Modal app is `nightwatch-generic`; its CPU-only preflight imported the exact runtime modules and returned both registered adapter identities before the paid candidate stage.

Real contract `contract-39056bbfd17e7fea529aa7db` binds Gemma revision `dcc83ea841ab6100d6b47a070329e1ba4cf78752`, adapter `scam-v0-de1e6009-2d77e636-c0e947096d`, dataset digest `707ce5c6b942377368c6d5dabae8084618ceb549f516ed78a83a2e9b9b959c80`, exact adapter label order, fixed release thresholds, one training attempt, and a 20-GPU-minute ceiling. Mission `nightwatch-live-fe8a4e9d756508004f9214de` sealed six entries and terminal head `a738d0dafde538062d63dfbe6b5fd1540a261b303af5a74155397fa9e6d4bd0b`.

The baseline scan discovered 14 errors across 92 cases. Gemini 3.6 Flash diagnosed the observed boundary; three Google ADK specialists authored 32 rows that passed schema, label, uniqueness, and leakage validation. One Modal call trained candidate `candidate-39056bbfd17e7fea529aa7db-00056841ed` in 5.5246 measured training seconds. Deterministic code refused it: target gain was -0.1111, regression drop was 0.125, safety accuracy was 0.4583, and seven critical cases were missed. The terminal state is `refused_not_deployed`; the queue was empty afterward and no ERROR-level logs occurred after the final worker release.

The rollout exposed two fail-closed defects before completion. The first Modal baseline call lacked `google-api-core`; its create-only call and claim remain preserved, while recovery generation `g2` received a separate one-call allowance after a deployed CPU preflight. The curriculum schema originally trusted a model-authored specialist identity; two retries were rejected with HTTP 409 before training. The queue was paused, identity was moved to the orchestrator-owned invocation boundary, tests were added, and `selfservice-4` completed the same cycle. No failed attempt weakened policy, changed evidence, trained a candidate, or deployed a model. Candidate, rollback, and restored traffic were exercised for every promoted private revision while the queue was paused.

## Public self-service case release — August 20, 2026

Public revision `nightwatch-public-selfservice-case2` and private proof revision `nightwatch-public-verifier-selfservice-case2` run the same immutable service image digest `sha256:9532438a1a42d2cd0c9d6ca57265f16ed82e512f98a72d811e499cf6d1e26313`. The judge UI still defaults to the strongest hidden-regression refusal, with **Self-service run** added as a third case file. Its bundled projection is bound to terminal head `a738d0dafde538062d63dfbe6b5fd1540a261b303af5a74155397fa9e6d4bd0b` and excludes raw rows, dataset identity, model revision, Modal call IDs, and operator authority.

Zero-traffic candidates passed health, security-header, public allowlist, operator-route denial, desktop/mobile UI, and browser-console checks. Public proof `verify-a775cde912b516ceac9d501c5717dc59925f1ff6` then crossed the isolated Cloud Tasks queue, re-read all six Firestore entries, and returned `verified` for the exact terminal head. Both services were routed new → known-good → new; canonical health passed in every state. The queue drained, both new revisions had zero ERROR-level logs, public IAM remained `allUsers` invoker only, and verifier IAM remained restricted to `nightwatch-public-invoker`.

## Public guided self-service release — August 20, 2026

Public revision `nightwatch-public-guided-demo` runs immutable image digest `sha256:cb50091bc26f5cd41e67cd3453f995ded9206c9832eb2f78a278cb0c45bebfb1`. The judge surface now exposes a four-step, read-only projection of the real operator flow: model selection, evidence mapping, fixed release boundaries, and replay. The walkthrough fetches only the allowlisted self-service snapshot and progressively reveals its original six hash-chained entries. It never uploads data, starts compute, calls Gemini or Modal, reads Firestore, or reaches an operator route.

The zero-traffic candidate passed the complete walkthrough, refusal, and qualified-comparison paths with a clean browser console. Its public health response reported `operator_enabled: false`; the self-service snapshot resolved to terminal head `a738d0dafde538062d63dfbe6b5fd1540a261b303af5a74155397fa9e6d4bd0b`; and a public operator POST returned 404. Traffic was promoted to the new revision, rolled back to known-good revision `nightwatch-public-selfservice-case2`, health-checked, and restored to `nightwatch-public-guided-demo`.

Visual follow-up revision `nightwatch-public-logo-completion` runs immutable image digest `sha256:943ae97eb59e087a7c697534439c53eb47aa52854a5780c898c30f69c83dcfee`. It adds the existing transparent Nightwatch wordmark only after the verified self-service replay reaches its refused terminal state. The zero-traffic candidate loaded the original 600×275 PNG, rendered without overflow at desktop and 390-pixel widths, kept a clean browser console, and returned 404 for the public operator route. Canonical traffic was routed to the branded revision, rolled back to healthy revision `nightwatch-public-guided-demo`, and restored. `nightwatch-public-logo-completion` now serves 100% of canonical traffic with no ERROR-level logs; rollback routes 100% traffic to `nightwatch-public-guided-demo`.

## Public Mission Theater release — August 20, 2026

Public revision `nightwatch-public-mission-theater-0afb0e2` runs immutable image digest `sha256:c93387970a3010800fd5a67e29322c163d199caf6cc12c954325a6022c161536`. The bare judge URL now opens a 30-second Mission Theater before the detailed evidence ledger. It presents one real handoff at a time, keeps the production/candidate authority boundary visible throughout, and ends at the deterministic refusal. Every displayed metric and artifact hash is derived from the allowlisted self-service journal; the walkthrough starts no compute and exposes no operator capability.

The zero-traffic candidate passed the full refusal-to-evidence path at desktop and 390-pixel widths with 16-pixel desktop body copy, 15-pixel mobile body copy, no horizontal overflow, and clean browser consoles. Health remained `public_redacted` with `operator_enabled: false`; the self-service journal returned all six entries and exact terminal head `a738d0dafde538062d63dfbe6b5fd1540a261b303af5a74155397fa9e6d4bd0b`; the public operator route returned 404; and the revision produced no ERROR-level logs. Production traffic was routed to the release, rolled back to known-good revision `nightwatch-public-header-logo-ec0d5aa`, health-checked, and restored. The service remains capped at one instance with 512 MiB memory, uses the dedicated `nightwatch-public` service account, and grants only `roles/run.invoker` to `allUsers`.

## Unified judge experience release — August 20, 2026

Commit `bb46fba` runs on public revision `nightwatch-public-unified-bb46fba` from immutable image digest `sha256:09a2789b657f54efad02957b1fff8c2d96449c247919c633588ad5b8a5cc4898`. The canonical judge URL now presents one evidence-derived experience: a nine-node execution graph that replays the six immutable handoffs, activates the three Gemini repair specialists in parallel, reveals the hidden routine-recall regression, and leaves the production boundary unchanged. The qualified retained case uses the same graph as counter-proof that the deterministic gate can also pass a candidate without deploying it.

The zero-traffic candidate passed the live refusal playback, qualified comparison, node inspection, public health, immutable journal, security-header, and operator-route-denial checks with a clean browser console. Its release health reports `bb46fba`; the service continues to run as `nightwatch-public@nightwatch-agentic-0992.iam.gserviceaccount.com`, is capped at one instance with 512 MiB memory, and exposes only `roles/run.invoker` to `allUsers`. No ERROR-level logs were present before or after promotion. Rollback was exercised by routing 100% traffic to `nightwatch-public-mission-theater-0afb0e2`, confirming healthy public mode, and restoring `nightwatch-public-unified-bb46fba`. The Mission Theater revision is the immediate rollback target.

## Enable the private Mission Control launch

The implemented self-service release exposes four operator APIs only on the authenticated `nightwatch-evidence` service and only when `NIGHTWATCH_OPERATOR_MODE=1`:

- `GET /api/operator/capabilities` returns pinned models, registered baseline adapters, format limits, and the approved compute grid;
- `POST /api/operator/datasets` accepts one bounded CSV or JSONL file and stores canonical, content-addressed bytes;
- `POST /api/operator/contracts` validates model, dataset mapping, suites, labels, release policy, and compute limits before creating an immutable contract;
- `POST /api/operator/missions` accepts only that frozen `contract_id` plus a 16–128 character `Idempotency-Key`.

The service derives the cycle ID from the contract and idempotency key. Callers cannot submit code, URLs, storage URIs, arbitrary models, runtimes, attempts, or deployment actions. The public service keeps `NIGHTWATCH_PUBLIC_MODE=1`, never sets operator mode, and returns 404 for every operator route.

This release is listed in the deployed acceptance record above. Any later change must repeat the zero-traffic rehearsal, CPU-only Modal preflight, rollback drill, and one-contract acceptance run before promotion.

Before enabling the route, preserve the existing private Cloud Run IAM policy and give the `nightwatch-evidence` runtime identity only these additional capabilities:

- enqueue tasks to `nightwatch-missions`;
- act as `nightwatch-missions-invoker` when creating that task.
- create and read objects under the private mission bucket's `operator/` prefix. Bucket-level public access prevention remains enforced.

Configure the private service with the existing mission queue location, name, canonical worker URL, invoker service account, mission artifact bucket, and `NIGHTWATCH_MODAL_CONNECTED=1` after the worker connection is verified. Modal credentials belong only on the worker. Do not copy credentials, these settings, or these permissions to `nightwatch-public`. The worker uses Vertex AI through ADC and `roles/aiplatform.user`; the dynamic workflow invokes the Gemini/ADK diagnostician and three parallel curriculum authors between a create-only Modal baseline call and one create-only training call.

## Verify the live mission

This request binds the task to the exact Firestore head. Keep the identity token in memory and change the idempotency key for a new verification intent.

```bash
NW_ID_TOKEN="$(gcloud auth print-identity-token)"
curl --fail --silent --show-error \
  --request POST \
  --header "Authorization: Bearer ${NW_ID_TOKEN}" \
  --header 'Content-Type: application/json' \
  --header 'Idempotency-Key: operator:replace-with-unique-request' \
  --data '{"expected_head_hash":"7bc281853fd88a253f895165e7edc4ebc3f1bc9eafb1ddf1da99348be096323d"}' \
  https://nightwatch-evidence-w3a6oefsma-uc.a.run.app/api/missions/nightwatch-v2-qualification/verifications
unset NW_ID_TOKEN
```

A new request returns HTTP 202 with `status: queued`. Replaying the same key returns the same verification ID with `status: already_accepted`; it does not create a second receipt.

## Build and deploy by digest

```bash
RELEASE="$(git rev-parse --short HEAD)"
IMAGE="us-central1-docker.pkg.dev/nightwatch-agentic-0992/nightwatch/evidence:${RELEASE}"
gcloud builds submit . \
  --project nightwatch-agentic-0992 \
  --region us-central1 \
  --config cloud/service-build.yaml \
  --substitutions "_IMAGE=${IMAGE}" \
  --timeout 1200s
gcloud artifacts docker images describe "${IMAGE}" \
  --project nightwatch-agentic-0992 \
  --format='value(image_summary.digest)'
```

Deploy only an immutable `IMAGE@sha256:...` reference. Preserve the existing service accounts, min/max instance limits, concurrency, timeouts, queue configuration, and private IAM policies shown above.

The public service uses the same immutable image with `NIGHTWATCH_PUBLIC_MODE=1`. Its runtime identity may enqueue only to `nightwatch-public-verifications`, attach only `nightwatch-public-invoker`, and read only the isolated public-proof receipt bucket. Do not grant it a Firestore role. The private public-proof verifier runs with both `NIGHTWATCH_WORKER_MODE=1` and `NIGHTWATCH_PUBLIC_WORKER_MODE=1`; it refuses every task except one of the bundled mission IDs with its exact bundled head and a server-issued receipt ID from the current or previous five UTC-minute buckets. Public mode reads only `/app/public-missions` and ignores caller idempotency: the server derives one task identity per mission per UTC minute. Cloud Tasks therefore deduplicates repeated clicks inside the minute, while a later minute creates a genuinely fresh Firestore read and create-only receipt. Legacy fixed receipt IDs remain readable for rollback compatibility. The receipt API reports Cloud Storage's authoritative object creation time.

## Roll back

List ready revisions, route all traffic to the selected known-good revision, verify the authenticated mission endpoint, and then inspect 5xx logs.

```bash
gcloud run revisions list \
  --service nightwatch-evidence \
  --project nightwatch-agentic-0992 \
  --region us-central1
gcloud run services update-traffic nightwatch-evidence \
  --project nightwatch-agentic-0992 \
  --region us-central1 \
  --to-revisions REVISION_NAME=100
```

Never add unauthenticated access to `nightwatch-evidence` or `nightwatch-verifier`. Only `nightwatch-public`, running in public mode under its dedicated identity, is designed for unauthenticated access.
