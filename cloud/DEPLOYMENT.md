# Deployment runbook

Nightwatch separates its private operator surface, public judge surface, and private verifier in `nightwatch-agentic-0992`.

## Deployed resources

- `nightwatch-evidence`: control API and UI, Firestore read-only, maximum two instances.
- `nightwatch-public`: public redacted UI/API, no Firestore permission, maximum one instance.
- `nightwatch-public-verifier`: private fixed-proof worker, existing Firestore read-only worker identity, maximum one instance and one concurrent request.
- `nightwatch-verifier`: Cloud Tasks worker, Firestore read-only, maximum one instance and one concurrent request.
- `nightwatch-mission-control`: private operator trigger with enqueue-only access, maximum one instance.
- `nightwatch-mission-worker`: private Gemini/ADK + Modal stage worker, maximum one instance and one concurrent request.
- `nightwatch-specialist-target`: private A2A Target Repair agent, Vertex AI user only, maximum one instance.
- `nightwatch-specialist-safety`: private A2A Safety Boundary agent, Vertex AI user only, maximum one instance.
- `nightwatch-specialist-regression`: private A2A Regression Guard agent, Vertex AI user only, maximum one instance.
- `nightwatch-missions`: one dispatch per second, one concurrent stage, and three bounded attempts.
- `nightwatch-public-verifications`: isolated public queue with the same one-per-second, one-concurrent, 30-second retry limits.
- `nightwatch-verifications`: one dispatch per second, one concurrent dispatch, three configured attempts within a 30-second retry window.
- `nightwatch-agentic-0992-public-verification-receipts`: isolated public-proof bucket with public access prevention and seven-day deletion.
- `nightwatch-agentic-0992-verification-receipts`: uniform bucket-level access, public access prevention, seven-day retention.
- `nightwatch-agentic-0992-mission-artifacts`: regional create-only mission artifacts and external-call claims, public access prevention, 30-day lifecycle.
- `nightwatch-tasks-invoker`: OIDC identity whose only application permission is invoking `nightwatch-verifier`.
- `nightwatch-missions-invoker`: OIDC identity whose only application permission is invoking `nightwatch-mission-worker`.

The canonical private control URL is `https://nightwatch-evidence-w3a6oefsma-uc.a.run.app`. Use the canonical `*.a.run.app` worker URL as both the Cloud Tasks target and OIDC audience; the alternate numeric hostname is not interchangeable for this purpose.

The canonical public judge URL is `https://nightwatch-public-w3a6oefsma-uc.a.run.app`. Commit `3ccbd0b` is the current production release. The public, authenticated, and both verifier services run `*-a2z-3ccbd0b` revisions from immutable service image digest `sha256:cbca4249b396c2eeb53b4b193abff3c844ceb99f9cc124aab2e8c05b1025c5c6`. Mission control and the stage worker run the same release suffix from mission digest `sha256:61ef9d7728178455aa2c23ce6bf456e597e7d009a1c30415191db55cdecb50db`. The three specialist services run the same release suffix from specialist digest `sha256:a4512e252f57ea43e1f445f41855c1aa1d1eb932db6b335772dd42c3a29c9eea`. The judge view defaults to the adaptive-fleet refusal mission and exposes only its bundled, strictly redacted evidence.

Historical acceptance mission `nightwatch-scam-20260814-001` traversed all six stages unattended in 94 seconds and qualified a new cycle-bound adapter on the earlier `scam-ff4f` mission revisions. Its terminal Firestore head is `3e7ff1420b51b9accfe4bd325c4faf00d89823d1db2bcbcac08eda6b0a916930`; private receipt `verify-1b69f5647d8003263b96eb03f185b9f653966d3a` independently sealed all six entries. The candidate reached 36/36 target, 24/24 safety, and 28/32 regression cases with zero critical misses and zero benign blocks. It remains qualified, not deployed.

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

## Independent specialist proof release — August 20, 2026

Mission `nightwatch-live-a786ae339253954371f524f8` is the primary judge case. The worker evaluated the frozen 92-case contract itself and discovered 14 baseline errors before summoning Gemini. The diagnostician delegated three distinct ADK briefs. Target Repair sealed 10 rows at `b9b22d431cee62bc6ae4d1676c95bffd3f833bf976ce4131eefca2b94dc245be`; Safety Boundary sealed 12 rows at `c90a075f4c5d0d9c9c2d26773cfd88946bbea5c30c2d67ce942f0596ddf61124`; Regression Guard sealed 9 rows at `f4bafafbfaf6f607aaf0f0d4327c3603e0efea5d66111a748f61d938b25a360e`. Each artifact is create-only, retry-safe, identity-bound, and independently inspectable before validation merges the 31-row curriculum.

One Modal attempt trained for 3.3019 measured seconds. Deterministic evaluation refused the candidate after target accuracy fell from 83.3% to 75.0%, safety accuracy from 95.8% to 45.8%, and regression accuracy from 78.1% to 56.3%; seven critical misses and four failed invariants kept production unchanged. The six-entry Firestore chain terminates at `1d84c10b244a1261d3b1f16f0348f3d68d5c2bfeb4b1d35e4315c171b18379ee` with `refused_not_deployed`.

Public, authenticated, verifier, and mission-worker zero-traffic candidates passed readiness and exact configuration checks before promotion. The public candidate returned the six-entry redacted projection with the three unique specialist receipts, emitted the full security-header policy, and returned 404 for the operator route. Desktop and 390-pixel browser rehearsals had no console errors or horizontal overflow. Public verification `verify-fe62cc2e46b3bdf2d5f3fb0ffd38d1c270e4f98c` crossed the isolated Cloud Tasks queue, re-read the exact Firestore head, and sealed a six-entry create-only receipt at `2026-08-21T03:41:14.944000Z`. This identifier records the successful rollout check; it is not a permanent public lookup URL. The API deliberately accepts only the current minute bucket and a five-minute grace window, while the sealed Cloud Storage object follows the separate retention policy documented above.

The final revisions are `nightwatch-public-agentproof2`, `nightwatch-public-verifier-agentproof2`, `nightwatch-evidence-agentproof2`, and `nightwatch-mission-worker-agentproof2`; each reports release `agentproof-20260820`. Rollback was exercised with both queues empty by routing public traffic to `nightwatch-public-unified-bb46fba`, public verifier traffic to `nightwatch-public-verifier-selfservice-case2`, authenticated traffic to `nightwatch-evidence-selfservice-2b`, and worker traffic to `nightwatch-mission-worker-selfservice-4`. Public health passed in the rolled-back state and all four services were restored. The final revisions have zero ERROR-level logs; public IAM exposes only `roles/run.invoker` to `allUsers`, verifier IAM exposes only `roles/run.invoker` to `nightwatch-public-invoker`, and both queues are empty.

## Snowfield theme and wordmark release — August 20, 2026

UI commit `58f4131` runs on public revision `nightwatch-public-snowfield` and authenticated revision `nightwatch-evidence-snowfield` from the same immutable image digest `sha256:e09446faf187ad29fd2ee9999e13be142f68ca3125ecffe54791b6747afb9a5b`. The release restores the real Nightwatch wordmark as the centered desktop header anchor, keeps a readable mobile treatment, and adds a persistent Night/Snowfield appearance control. Snowfield uses a warm off-white surface rather than a generic white dashboard; measured body, muted, and accent contrast ratios are 7.08:1, 7.08:1, and 4.85:1.

The zero-traffic public candidate passed both themes, preference persistence after reload, 1440-pixel and 390-pixel layouts, zero horizontal overflow, clean browser logs, security headers, redacted health, and operator-route denial. Both services preserved their prior service accounts, environment, concurrency, and scale caps. Traffic was promoted, routed back to `nightwatch-public-agentproof2` and `nightwatch-evidence-agentproof2`, health-checked in the rolled-back state, and restored to the Snowfield revisions. No verifier or mission-worker rollout was required because neither API nor evidence semantics changed.

## Judge-first verified mission release — August 20, 2026

Commit `8e874be` runs on public revision `nightwatch-public-judgeux-8e874be` and authenticated revision `nightwatch-evidence-judgeux-8e874be` from the same immutable service image digest `sha256:eb82e720e98a0e90016a24d011ffea1976445a35f058e137ef95ee8191023417`. The judge surface now opens on the completed, verified nine-node mission and its deterministic refusal instead of an artificial zero-progress state. Replay is explicitly optional, the three specialist assignments and sealed row counts are visible without inspector clicks, live Google Cloud proof is present from first paint, and the 390-pixel layout becomes a vertical execution sequence rather than a horizontally discoverable canvas.

The zero-traffic candidates passed public redacted health, authenticated private health, operator capability preservation, public operator-route denial, exact six-entry mission-head validation, CSP/frame/no-sniff headers, both themes, 1440-pixel and 390-pixel layouts, the complete replay lifecycle, zero horizontal overflow, and clean browser consoles. Both revisions use the exact new digest under the unchanged `nightwatch-public` and `nightwatch-evidence` service accounts. The mission and public-verification queues were empty, and neither revision emitted ERROR-level logs.

Production traffic was promoted to the new pair, routed back to known-good revisions `nightwatch-public-snowfield` and `nightwatch-evidence-snowfield`, health-checked with public mode still redacted and private operator mode still enabled, and restored to the new pair. Final canonical health reports release `judgeux-8e874be`; the primary public mission still resolves to six entries and terminal head `1d84c10b244a1261d3b1f16f0348f3d68d5c2bfeb4b1d35e4315c171b18379ee`. No verifier, mission-worker, IAM, queue, dataset, Gemini, or Modal changes were required.

## Evidence-first judge dossier release — August 21, 2026

UI commit `6f8aa6e` runs on public revision `nightwatch-public-dossier-6f8aa6e` from immutable service image digest `sha256:e002104d3cc278af1e4531fe9ca072f280f2f55880d28ac0fd3df01053b057f1`. The judge experience now presents the retained mission as an evidence-first product narrative: autonomous baseline discovery, Gemini diagnosis, three independently inspectable ADK specialist artifacts, one bounded Modal training attempt, deterministic four-invariant release adjudication, the six-entry hash chain, and a real qualified-but-not-deployed counter-case. The release-boundary interaction is a read-only replay and cannot start training or modify evidence.

The zero-traffic candidate passed 22 frontend evidence tests, the production Vite build, public redacted health, exact six-entry mission-head validation, CSP/frame/no-sniff headers, public operator-route denial, dark and Snowfield themes, desktop/tablet/exact 390-pixel layouts, zero horizontal overflow, specialist selection, outcome switching, and the complete four-check refusal animation. The deployed revision retains the dedicated `nightwatch-public` service account, 512 MiB memory, one CPU, 20-request concurrency, 15-second timeout, scale-to-zero/max-one instance boundary, and the existing isolated public-verification configuration. It emitted no ERROR-level logs before or after promotion.

Traffic was promoted to the new revision, routed back to known-good revision `nightwatch-public-judgeux-8e874be`, health-checked with `operator_enabled: false` and `visibility: public_redacted`, and restored to `nightwatch-public-dossier-6f8aa6e`. The previous judge-first revision remains the immediate rollback target. No private operator, verifier, mission worker, IAM, queue, Firestore, Gemini, Modal, dataset, or release-policy change was required.

## Agent-proof judge refinement — August 21, 2026

UI commit `9d2e768` runs on public revision `nightwatch-public-judgeproof-9d2e768` from immutable service image digest `sha256:3c94f181708a6dad62517838a61ca474b56e32e1cda27d5796192b568d711649`. The opening viewport now names the exact Google stack, every specialist card exposes its real sealed row count and shortened immutable artifact hash, and the deterministic release boundary runs once when it enters the viewport. The manual replay remains available; reduced-motion clients resolve the checks without timed choreography.

The zero-traffic candidate passed all 22 frontend evidence tests, the production Vite build, public-redacted health, the exact six-entry refusal projection and terminal head, required security headers, operator-route denial, desktop and 390-pixel layouts, both refused and qualified viewport-triggered gates, specialist receipt rendering, and a clean browser console. The revision preserves the dedicated public service account, one CPU, 512 MiB memory, 20-request concurrency, 15-second timeout, scale-to-zero/max-one boundary, existing queue settings, and zero ERROR-level release logs.

Canonical traffic was promoted to the new revision, routed back to healthy known-good revision `nightwatch-public-dossier-6f8aa6e`, and restored to `nightwatch-public-judgeproof-9d2e768`. The dossier revision is the immediate rollback target. No private operator, verifier, mission worker, IAM, queue, Firestore, Gemini, Modal, dataset, evidence, or release-policy change was required.

UI fix `a7aef07` runs on public revision `nightwatch-public-activecase-a7aef07` from immutable service image digest `sha256:b00d0a67f283aefb0415e1e9df99bcc1d3c8e90d0f919ab0629e886186cbd700`. Selecting the already-active refused case is now a no-op instead of clearing the loaded mission without changing the fetch key, which previously left the judge surface on its loading state.

The zero-traffic candidate passed all 23 frontend evidence tests, the production Vite build, public-redacted health, security headers, operator-route denial, the complete refusal animation, and the exact selected-case reproduction with a clean browser console. Canonical production passed the same reproduction after promotion. Traffic was routed back to healthy revision `nightwatch-public-judgeproof-9d2e768` and restored to the fixed revision; the judgeproof revision remains the immediate rollback target. The fixed revision has no ERROR-level logs, and no private operator, verifier, mission worker, IAM, queue, Firestore, Gemini, Modal, dataset, evidence, or release-policy change was required.

Qualified-case projection fix `ff0cf26` runs on public revision `nightwatch-public-qualified-ff0cf26` from immutable service image digest `sha256:25dd2407bf27ceeb982bb1933353c94c77dd125f4bc7b1da31c9f8d937261ddd`. The judge dossier now derives the retained qualification's discovery, curriculum, training, and evaluation panels from its real retained evidence instead of applying the live-journal schema and rendering missing values. The passing case exposes its 14 baseline errors, exact 92-case suite counts, five Gemini-authored repair batches, 416-row content-addressed curriculum, 49.9125-second Modal L4 run, and measured baseline-to-candidate results.

The zero-traffic candidate passed all 23 frontend evidence tests, the production Vite build, canonical qualified-case rendering, public-redacted health, required security headers, and public operator-route denial. The service retained its existing dedicated identity, one CPU, 512 MiB memory, 20-request concurrency, 15-second timeout, and max-one-instance boundary. Traffic was promoted, routed back to healthy revision `nightwatch-public-activecase-a7aef07`, and restored to the fixed revision. The active-case revision is the immediate rollback target; the new revision has no ERROR-level logs, and no private operator, verifier, worker, IAM, queue, Firestore, Gemini, Modal, dataset, or release-policy change was required.

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

Configure the private service with the existing mission queue location, name, canonical worker URL, invoker service account, mission artifact bucket, and `NIGHTWATCH_MODAL_CONNECTED=1` after the worker connection is verified. Modal credentials belong only on the worker. Do not copy credentials, these settings, or these permissions to `nightwatch-public`. The worker uses Vertex AI through ADC and `roles/aiplatform.user`; the dynamic workflow invokes the Gemini/ADK diagnostician, resolves the bounded fleet through Agent Registry, and calls three private ADK specialists over A2A between a create-only Modal baseline call and one create-only training call.

## Adaptive Agent Registry fleet — August 28, 2026 UTC

Nightwatch now deploys Target Repair, Safety Boundary, and Regression Guard as three independent, IAM-protected Cloud Run services. Each runs the same immutable code image under a different service account, has scale-to-zero/max-one configuration, and holds only `roles/aiplatform.user` at project scope. The mission worker has `roles/agentregistry.viewer` and service-level `roles/run.invoker`; it has no registry-write authority.

The operator contract schema v2 pins each specialist's Agent Registry URN, Agent Card SHA-256, HTTPS origin, service account, and capability tag. Gemini emits capabilities from a fixed taxonomy. Deterministic routing adds the mandatory regression guard, searches Agent Registry, rejects anything outside the frozen roster, and writes the selected plan into the immutable `diagnosed` artifact before any A2A invocation. A retry therefore cannot pick a different agent. The existing in-process schema-v1 path remains the exercised rollback for retained missions; there is no silent fallback from a v2 mission.

One-shot Cloud Run Job execution `nightwatch-registry-spike-cxw9g` proved the final three-service path under the real `nightwatch-mission-worker` identity. Agent Registry returned all three frozen URNs and exact card hashes, and each private A2A call returned a distinct request/response receipt. Cloud Logging recorded schema `nightwatch.adaptive-fleet-proof.v1`; the job exited successfully with no user token or temporary impersonation grant. An earlier execution deliberately failed closed when Safety still served its previous immutable card. The mismatch was corrected by immutable revision rollout rather than weakening the pin, and the unchanged proof then passed.

Frozen contract `contract-8d1d1940d6190b2b50ef7dd8` then exercised the path as a real model-repair product, not a connectivity spike. Mission `nightwatch-live-ac7c9d317783b6af4e543b1d` scanned the pinned Gemma checkpoint against all 92 cases, found 14 baseline errors, and sealed a three-agent Registry plan before delegation. Target Repair returned 12 rows, Safety Boundary 8, and Regression Guard 10. Every handoff retains its Agent Card, A2A request, A2A response, and artifact SHA-256 independently.

The single allowed Modal attempt trained `candidate-01` from those 30 validated rows in 3.9603 measured seconds. Target accuracy improved from 30/36 to 33/36, but safety fell from 23/24 to 15/24, regression fell from 25/32 to 22/32, and three critical cases were missed. All four fixed release invariants failed, so deterministic code wrote `refused_not_deployed`; the six-entry Firestore chain terminates at `6d7d4c0ae6374a6b0230a342a3b0caff44c3fc2586f33173744ac2df2250329f` and production remained unchanged.

The first dispatch failed closed because the isolated Modal app still parsed the previous contract schema. After its parser was updated, the original deterministic Cloud Tasks name had already exhausted its three retry attempts and remained tombstoned. Recovery generation `g2` produced a new deterministic task identity for the same frozen contract and cycle; it did not create a second mission, change evidence, or authorize a second training attempt. Worker revision `nightwatch-mission-worker-adaptive-task-g2` and authenticated revision `nightwatch-evidence-adaptive-task-g2` completed that preserved mission.

## Adaptive-fleet judge release — August 28, 2026 UTC

Public revision `nightwatch-public-registry-a2a-final`, authenticated revision `nightwatch-evidence-registry-a2a-final`, and verifier revision `nightwatch-public-verifier-registry-a2a-final` run the same immutable service digest `sha256:90b9b7569d4b1f960212ac76ad38e02571fbddd4bffdfed49c0d673a817076d5`. The public projection exposes the selected Registry URNs, Agent Card hashes, A2A request/response receipt hashes, artifact hashes, row counts, measurements, and terminal decision. The judge UI separately publishes one newly authored, non-customer safety-case excerpt only when the exact retained evaluation artifact hash matches. All other raw cases remain excluded, together with dataset identity, model revision, endpoint origins, service accounts, Modal call identity, private artifact locations, and credentials. The public operator route returns 404.

The exact zero-traffic candidates passed redacted/public and authenticated/private health, six-entry mission loading, operator capability preservation, CSP/frame/no-sniff headers, public route denial, both real outcomes, a complete refusal replay, desktop 1440×900 and mobile 390×844 rendering, zero page-level horizontal overflow, and clean browser logs. The retained qualified case deliberately omits Agent Registry and A2A from its per-case stack because that historical mission predates the adaptive fleet.

After promotion, public proof `verify-c20c18c0e306d9d0ff533be85e685a6426503d2b` crossed the isolated Cloud Tasks queue. The private verifier reread all six Firestore entries and sealed exact head `6d7d4c0ae6374a6b0230a342a3b0caff44c3fc2586f33173744ac2df2250329f` at `2026-08-28T02:56:44.982000Z`. This is a rollout record rather than a permanent public lookup identity.

Rollback was exercised by routing public traffic to `nightwatch-public-qualified-ff0cf26`, authenticated traffic to `nightwatch-evidence-adaptive-task-g2`, and verifier traffic to `nightwatch-public-verifier-agentproof2`. All three reported healthy in that state and were restored to the final revisions. The public-verification and mission queues were empty afterward; the three final revisions had no ERROR-level logs. IAM remained unchanged: only the public judge service grants `allUsers` invoke access, the verifier accepts only `nightwatch-public-invoker`, each specialist accepts only `nightwatch-mission-worker`, and each specialist holds only `roles/aiplatform.user` at project scope.

## Judge gate sequencing release — August 28, 2026 UTC

Public revision `nightwatch-public-scroll-82f2326` runs immutable digest `sha256:214ecdff84f95e122f31ccd7dd9a93b61cf8c864a55840b58ff0459e4bd17fdd`. The judge-page gate now waits for smooth scrolling to settle before beginning its four deterministic checks; the former viewport-triggered auto-run was removed. Reduced-motion clients still jump to the boundary and begin immediately.

The zero-traffic candidate passed all 25 frontend evidence tests, the production Vite build, public-redacted health, required security headers, public operator-route denial, the real six-entry refusal projection, and both browser gate paths. In the live browser, refusal stayed pending throughout the scroll before ending `Four of four failed`; qualification followed the same sequence before ending `Four of four passed`. The service retained its dedicated public identity, one CPU, 512 MiB memory, 20-request concurrency, 15-second timeout, and scale-to-zero/max-one boundary.

After promotion, canonical health reported release `82f2326`. Rollback was exercised by routing all public traffic to healthy revision `nightwatch-public-registry-a2a-final`, verifying public-redacted health, and restoring `nightwatch-public-scroll-82f2326`. The restored revision reported healthy and had no ERROR-level logs. No private operator, verifier, mission worker, IAM, queue, Firestore, Gemini, Modal, dataset, evidence, or release-policy change was required.

## Governed follow-up release — August 28, 2026 UTC

Public revision `nightwatch-public-governed-final` and authenticated revision `nightwatch-evidence-governed-final` run immutable service digest `sha256:00ddb97fd97e2564fde1f3d069a198bc5c1d224e36f8ee7b67e846aeea5dff52`. Mission-worker revision `nightwatch-mission-worker-governed-preflight` runs immutable digest `sha256:efc1863a130c59b0d1753010d261ce76a74a387630a887db86b2deb7a8234813`.

Terminal refusal `nightwatch-live-ac7c9d317783b6af4e543b1d` produced create-only proposal `followup-c6cf05ae664966c7d7a4c756`, content hash `c6cf05ae664966c7d7a4c756d611b3d5b2ce6d2f8b3a2c2a78d07cd596578655`. The proposal pins its parent contract, terminal Firestore head, evaluation digest, four failed invariants, three bounded repair emphases, one-attempt/20-GPU-minute maximum, and lineage depth one. It has neither execution nor deployment authority. No approval or child mission was created because no different frozen evidence and separate compute authorization were supplied.

The zero-traffic candidates passed all 284 Python tests, all 28 frontend tests, the production Vite build, redacted/public and authenticated/private health, the exact six-entry mission projection, genuine follow-up identity, CSP/frame/no-sniff headers, public drafting and approval-route denial, desktop rendering, and 390-by-844 mobile rendering with no horizontal overflow. Cloud Run marked the private worker revision `Ready` and `ContainerHealthy`; its direct endpoint remained inaccessible to the operator account because the worker IAM policy was intentionally not relaxed. All three release revisions had no ERROR-level logs.

Canonical public and authenticated traffic was promoted, rolled back to healthy revisions `nightwatch-public-scroll-82f2326` and `nightwatch-evidence-registry-a2a-final`, verified there, and restored to the governed revisions. Mission-worker traffic moved from `nightwatch-mission-worker-adaptive-task-g2` to the governed worker while the queue was empty. Fresh public proof `verify-ce3695f6c6a02060a2ba64898c8ad67d808bc431` then reread all six Firestore entries and sealed exact head `6d7d4c0ae6374a6b0230a342a3b0caff44c3fc2586f33173744ac2df2250329f` at `2026-08-28T22:51:02.349000Z`.

No service account, IAM grant, queue limit, instance cap, production model pointer, release threshold, retained evidence object, or deployment authority changed in this release.

## Full-system hardening release — August 29, 2026 UTC

Commits `565ae3d` and `3ccbd0b` harden the governed follow-up lifecycle, public projection validation, queue-failure recovery, dependency locking, CI, and production operations. The final correction checks in the synthetic 150-row development artifact required by the retained mission rollback path. GitHub Actions run `33232222247` passed 290 Python tests, 29 frontend tests, four exact production dependency audits, the npm production audit, the Vite production build, and all three Docker builds.

Cloud Build produced immutable service digest `sha256:cbca4249b396c2eeb53b4b193abff3c844ceb99f9cc124aab2e8c05b1025c5c6`, mission digest `sha256:61ef9d7728178455aa2c23ce6bf456e597e7d009a1c30415191db55cdecb50db`, and specialist digest `sha256:a4512e252f57ea43e1f445f41855c1aa1d1eb932db6b335772dd42c3a29c9eea`. All nine `*-a2z-3ccbd0b` candidates were deployed at zero traffic. The public candidate loaded all three retained outcomes, reported release `3ccbd0b`, returned 404 for every operator route, and emitted the expected CSP, frame, content-type, and cache controls. Authenticated candidate checks verified the private capability contract, both verifier modes, specialist readiness, and fail-closed request validation on mission control and the stage worker without launching a mission.

The specialists, mission worker, mission control, verifiers, authenticated service, and public service were promoted in dependency order. The mission queue and public-verification queue were empty before the rollout. The public, private, and mission-worker rollback paths were then exercised against `nightwatch-public-governed-final`, `nightwatch-evidence-governed-final`, and `nightwatch-mission-worker-governed-preflight`; each known-good revision served correctly before traffic returned to `3ccbd0b`. The restored public and private health contracts report the new release, the restored worker still rejects malformed task envelopes, and all new revisions have zero ERROR-level logs. Fresh public proof `verify-384a127eceab9c3cc248db658f81fbb92dceb92c` crossed the isolated queue, reread all six Firestore entries, and sealed terminal head `6d7d4c0ae6374a6b0230a342a3b0caff44c3fc2586f33173744ac2df2250329f` at `2026-08-29T04:08:20.256000Z`.

Cloud Monitoring API is enabled. Alert policy `14540923085365206789` watches sustained `nightwatch-public` Cloud Run 5xx traffic and routes to enabled email channel `10574075472569398232`; the checked-in runbook is linked from the alert documentation. Artifact Registry tag cleanup was attempted only for inventoried stale aliases, but the repository's tag-immutability policy rejected every deletion. That integrity control remains enabled, and no tag or digest was deleted.

## Verify the live mission

This request binds the task to the current adaptive-fleet mission and its exact Firestore head. Keep the identity token in memory and change the idempotency key for a new verification intent.

```bash
NW_ID_TOKEN="$(gcloud auth print-identity-token)"
curl --fail --silent --show-error \
  --request POST \
  --header "Authorization: Bearer ${NW_ID_TOKEN}" \
  --header 'Content-Type: application/json' \
  --header 'Idempotency-Key: operator:replace-with-unique-request' \
  --data '{"expected_head_hash":"6d7d4c0ae6374a6b0230a342a3b0caff44c3fc2586f33173744ac2df2250329f"}' \
  https://nightwatch-evidence-w3a6oefsma-uc.a.run.app/api/missions/nightwatch-live-ac7c9d317783b6af4e543b1d/verifications
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
