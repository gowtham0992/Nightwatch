# Public Cloud Run 5xx runbook

This alert means the credential-free judge experience returned server errors at a sustained rate above 0.01 requests per second for two minutes. Treat it as user-visible and respond immediately.

1. Open the canonical public URL and `GET /api/health`. Confirm whether the failure affects the page, the API, or both.
2. Inspect ERROR logs for `nightwatch-public` and identify the active revision.
3. Check the revision's readiness, image digest, environment, public IAM binding, and bundled public evidence paths.
4. If the active revision is responsible, route traffic to the previous healthy revision recorded in `cloud/DEPLOYMENT.md`.
5. Verify the canonical health endpoint, one allowlisted mission, one governed follow-up projection, security headers, and the denial of `/api/operator/capabilities`.
6. Confirm the alert closes and record the incident and rollback revision in `cloud/DEPLOYMENT.md`.

The rollback changes Cloud Run traffic only. It does not mutate Firestore, Cloud Storage evidence, model pointers, or mission state.
