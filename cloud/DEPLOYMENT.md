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

The canonical public judge URL is `https://nightwatch-public-w3a6oefsma-uc.a.run.app`. Release `scam-repair-e4819ce` runs revision `nightwatch-public-scam-e481-v2` from immutable image digest `sha256:c617d1458a0bd3bb4e3c944f1588d9e4396af801ce952ec07ef6d552f463c7e4`. The product view is bound to fresh mission `nightwatch-scam-20260814-001`, its exact terminal Firestore head, independent verification receipt, and GCS training and evaluation artifact identities. The previous known-good revision is `nightwatch-public-watchtower`; routing to it and restoring the scam-repair release were both exercised successfully on August 14, 2026.

The mission control and worker run immutable image digest `sha256:e3d09ce4d07c652c777034ca5c1c06c217d5862f09c87edbee9cbbe235665478` in revisions `nightwatch-mission-control-scam-ff4f` and `nightwatch-mission-worker-scam-ff4f`. Fresh scam mission `nightwatch-scam-20260814-001` traversed all six stages unattended in 94 seconds and qualified a new cycle-bound adapter. Its terminal Firestore head is `3e7ff1420b51b9accfe4bd325c4faf00d89823d1db2bcbcac08eda6b0a916930`; private receipt `verify-1b69f5647d8003263b96eb03f185b9f653966d3a` independently sealed all six entries. The candidate reached 36/36 target, 24/24 safety, and 28/32 regression cases with zero critical misses and zero benign blocks. It remains qualified, not deployed.

The rollback drill was exercised after the mission completed: traffic returned to `nightwatch-mission-control-00001-4cj` and `nightwatch-mission-worker-00002-s58`, then restored to the new revisions with no queued work and no ERROR-level release logs.

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

The public service uses the same immutable image with `NIGHTWATCH_PUBLIC_MODE=1`. Its runtime identity may enqueue only to `nightwatch-public-verifications`, attach only `nightwatch-public-invoker`, and read only the isolated public-proof receipt bucket. Do not grant it a Firestore role. The private public-proof verifier runs with both `NIGHTWATCH_WORKER_MODE=1` and `NIGHTWATCH_PUBLIC_WORKER_MODE=1`; it refuses every task except one of the two bundled mission IDs with its exact bundled head and a server-issued receipt ID from the current or previous five UTC-minute buckets. Public mode reads only `/app/public-missions` and ignores caller idempotency: the server derives one task identity per mission per UTC minute. Cloud Tasks therefore deduplicates repeated clicks inside the minute, while a later minute creates a genuinely fresh Firestore read and create-only receipt. Legacy fixed receipt IDs remain readable for rollback compatibility. The receipt API reports Cloud Storage's authoritative object creation time.

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
