# Deployment runbook

Nightwatch separates its private operator surface, public judge surface, and private verifier in `nightwatch-agentic-0992`.

## Deployed resources

- `nightwatch-evidence`: control API and UI, Firestore read-only, maximum two instances.
- `nightwatch-public`: public redacted UI/API, no Firestore permission, maximum one instance.
- `nightwatch-verifier`: Cloud Tasks worker, Firestore read-only, maximum one instance and one concurrent request.
- `nightwatch-verifications`: one dispatch per second, one concurrent dispatch, three configured attempts within a 30-second retry window.
- `nightwatch-agentic-0992-verification-receipts`: uniform bucket-level access, public access prevention, seven-day retention.
- `nightwatch-tasks-invoker`: OIDC identity whose only application permission is invoking `nightwatch-verifier`.

The canonical private control URL is `https://nightwatch-evidence-w3a6oefsma-uc.a.run.app`. Use the canonical `*.a.run.app` worker URL as both the Cloud Tasks target and OIDC audience; the alternate numeric hostname is not interchangeable for this purpose.

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

The public service uses the same immutable image with `NIGHTWATCH_PUBLIC_MODE=1`. Its runtime identity may enqueue to `nightwatch-verifications`, attach `nightwatch-tasks-invoker` to that task, and read the receipt bucket. Do not grant it a Firestore role. Public mode serves only `/app/public-mission.json`, replaces caller idempotency with `public:nightwatch-v2-proof`, and permits only the matching content-derived receipt ID.

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
