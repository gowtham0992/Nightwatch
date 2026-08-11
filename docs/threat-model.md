# Threat model

**Threat sentence:** a compromised or merely mistaken agent controls diagnoses, generated training rows, and model text; its prize is leaking hidden evaluation data or moving an unsafe adapter into production.

Nightwatch uses a full-hardening regime for the promotion path:

- Every JSONL boundary is typed, length-bounded, allowlisted, and duplicate-checked.
- Canonical prompt fingerprints block exact training/eval overlap across case, spacing, and Unicode normalization variants.
- Invalid, missing, duplicate, or extra predictions fail closed.
- The training job receives no hidden-eval path and its service account has no permission on that bucket.
- The evaluator cannot write the production pointer; the promoter cannot generate models or modify fixed policy.
- Promotion is code-scored against immutable policy. An LLM never supplies the verdict.
- Lifecycle entries can form a SHA-256 hash chain, making edits inside an existing local chain evident. No autonomous process writes real lifecycle history yet. The production version will store create-only records in Firestore and immutable artifacts in versioned Cloud Storage.
- Secrets enter through Secret Manager/environment only and are never included in reports or journal payloads.

**Public-service threat sentence:** an internet caller controls the URL path and request rate; its prize is Firestore read amplification or triggering paid model work. The current HTTP surface therefore has only bounded reads: mission IDs are allowlisted, a verified chain contains at most seven entries, Firestore calls time out, API responses are not cached, and no HTTP mutation or model-execution route exists. Rate and instance caps become required deployment controls before the service is public.

The local hash chain detects tampering but does not prevent a process with filesystem write access from replacing the entire journal. Cloud IAM, object versioning/retention, and independently stored head hashes are required before claiming production-grade immutability.
