# Threat model

**Threat sentence:** a compromised or merely mistaken agent controls diagnoses, generated training rows, and model text; its prize is leaking hidden evaluation data or moving an unsafe adapter into production.

Nightwatch uses a full-hardening regime for the promotion path:

- Every JSONL boundary is typed, length-bounded, allowlisted, and duplicate-checked.
- Canonical prompt fingerprints block exact training/eval overlap across case, spacing, and Unicode normalization variants.
- Invalid, missing, duplicate, or extra predictions fail closed.
- The training job receives no hidden-eval path and its service account has no permission on that bucket.
- The evaluator cannot write the production pointer; the promoter cannot generate models or modify fixed policy.
- Promotion is code-scored against immutable policy. An LLM never supplies the verdict.
- The retained lifecycle is stored as a bounded SHA-256 chain in Firestore. Every API read recomputes entry hashes, verifies links, and reconciles the mission head before returning evidence.
- Secrets enter through Secret Manager/environment only and are never included in reports or journal payloads.

**Control-service threat sentence:** an authenticated caller controls the mission ID, request body, and idempotency key; its prize is Firestore read amplification or queue amplification. Mission IDs and keys are allowlisted and length-bounded, request bodies are capped at 16 KiB, a verified chain contains at most seven entries, Google Cloud calls time out, API responses are not cached, and the service is capped at two instances. The control service remains IAM-protected.

**Public-service threat sentence:** anyone on the internet controls the URL, request body, headers, and request rate; their prize is private evidence disclosure or paid-work amplification. The public service has no Firestore permission and serves only a startup-validated, checked-in redaction of one mission. Its trigger requires the exact bundled head, discards caller idempotency, and resolves to one content-derived task and one receipt ID. Bodies are capped at 16 KiB, non-allowlisted missions and receipts return 404, the shared queue is throttled, and the service scales from zero with a hard instance cap. This bounds downstream work but is not a general-purpose public verification API.

The verification worker trusts Cloud Run IAM for caller identity; Cloud Tasks headers are correlation data, not authentication. Its OIDC invoker identity can call only the private worker. The runtime identity can read Firestore and create objects in one dedicated bucket, but it cannot modify missions or read, overwrite, or delete receipts. A generation-zero precondition makes retries a single effect.

The public JSON retains the original entry and head hashes so judges can see that the redaction is tied to the retained mission, but it cannot independently prove omitted payload fields. The private worker supplies the stronger proof by re-reading the live Firestore chain at that exact head. The hash chain detects entry or link tampering but does not make a project owner harmless. The current claim is narrower: application identities cannot rewrite the mission through Nightwatch, and verification receipts are create-only with seven-day bucket retention. This is not a claim of protection from project-owner compromise.
