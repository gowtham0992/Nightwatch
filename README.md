# Nightwatch Evolution

**AI can propose its own upgrade. It cannot approve it.**

Nightwatch is a release guardian for small production models. Deterministic analysis bounds a failing behavior, Gemini with Google ADK designs a targeted curriculum, Modal trains pinned Gemma candidates, and deterministic evaluation code qualifies a candidate only when it clears fixed regression and safety policy.

This project targets **The Taskmaster** track. One authenticated request now starts a bounded qualification mission on Google Cloud; Cloud Tasks carries it through diagnosis, Gemini curriculum design, Modal training, deterministic evaluation, and a qualified-or-refused terminal decision without further operator action. Production deployment is never authorized by this workflow.

![Nightwatch deployed architecture](docs/images/nightwatch-architecture.png)

## What works now

Two complementary real missions now exist. The retained qualification proves that policy v2 can qualify a candidate: Gemini 3.6 Flash and Google ADK generated a 32-example safety intervention; Modal trained pinned Gemma 3 270M and 1B candidates; and deterministic code refused the 270M candidate while qualifying the 1B candidate after a prediction-blind evidence audit.

The deployed Taskmaster path proves the product runs unattended. Mission `nightwatch-cloud-20260811-001` was started once through the private control service, then advanced through six Cloud Tasks-backed stages from `00:58:16` to `01:00:01 UTC`. Gemini generated a fresh 32-example curriculum, Modal performed one pinned 270M training run, and policy v2 **refused** the candidate because regression accuracy was 73.75% and defer recall was 60%, despite safety reaching the 90% floor. Nothing was deployed. Its six-entry Firestore head is `b75997fa00e6263d1e5139d1047ea04eef02ab25c4f0f12188cadf7ed1154a85`, independently sealed by create-only verification receipt `verify-ae7b0bc76f9623af88ee36746af149ed7fc6f179`.

**Hosted judge experience:** [open the public redacted proof](https://nightwatch-public-w3a6oefsma-uc.a.run.app/).

The mission archive switcher opens on the fresh unattended refusal and links to the retained earned qualification, so judges can compare both outcomes under the same deterministic policy without granting the public service access to Firestore or training credentials.

The qualified 1B candidate reached 86.25% regression accuracy, 93.3% safety accuracy, 70% target accuracy, and zero critical misses. It is **qualified, not deployed**, and the result is specific to the checked-in policy-v2 evidence—not a claim of universal model safety.

Each mission's six lifecycle stages are stored in Firestore as a transaction-safe SHA-256 chain. A private control service can only enqueue the approved manifest; a separate single-concurrency worker owns Gemini, artifact, and Modal access. Every stage artifact and external-call claim is create-only, so retrying the same task returns existing evidence instead of spending again. The public service still has no Firestore, Gemini, Modal, or mission-start permission and serves only the two checked-in redacted proofs.

## Run the evidence logbook UI

The single-screen UI in `web/` fetches `nightwatch-v2-qualification` from the evidence API, validates the bounded chain again in the browser, and fails closed instead of replacing unavailable cloud evidence with fixture data.

```bash
cd web
npm install
npm run dev
```

Use `npm test` for the adapter contract and `npm run build` for the production bundle. Local Vite development needs an API proxy or a local service; the deployed bundle and API share one Cloud Run origin.

## Run the evidence service

The control service exposes the static UI, `GET /api/health`, `GET /api/missions/<cycle_id>`, and an authenticated verification trigger. The trigger accepts an exact observed head plus an idempotency key; it can enqueue only the throttled verification worker and cannot launch training or alter promotion policy.

```bash
docker build --file containers/service.Dockerfile --tag nightwatch-service:local .
docker run --rm --publish 127.0.0.1:8080:8080 nightwatch-service:local
```

Without Google Application Default Credentials, the UI and shallow health check work locally while Firestore mission reads fail closed with HTTP 503. The deployed control identity has Firestore read-only access and enqueue permission on one queue. The worker has Firestore read-only access and create-only access on one receipt bucket.

The operator service remains IAM-protected. The public judge service uses a separate least-privilege identity and returns only the bundled redacted projection. See [the deployment runbook](cloud/DEPLOYMENT.md) for the exact resources, verification request, cost caps, and rollback path.

## Run the deterministic proof

Python 3.11+ is sufficient and the core has no runtime dependencies.

```bash
PYTHONPATH=src python -m nightwatch.cli gate-fixture \
  --candidate data/predictions/good_candidate.jsonl \
  --report artifacts/good-report.json

PYTHONPATH=src python -m nightwatch.cli gate-fixture \
  --candidate data/predictions/bad_high_score_candidate.jsonl \
  --report artifacts/bad-report.json

PYTHONPATH=src python -m pytest
```

## Generate curriculum with Gemini and Google ADK

The curriculum agent receives only an aggregate diagnosis—not hidden eval prompts. Set `GOOGLE_API_KEY` for the Gemini API or configure Vertex AI ADC, then run:

```bash
uv sync --extra agent
uv run python -m nightwatch.curriculum_agent \
  --diagnosis data/diagnosis/silent_failure.json \
  --output artifacts/generated-curriculum.jsonl \
  --examples 96
```

The pinned architect model is `gemini-3.6-flash`; `gemini-3.5-flash` is the fallback if availability requires it.

## Run the real Gemma spike

Gemma access requires accepting its Hugging Face terms and providing `HF_TOKEN` through the environment or Secret Manager. Generate the 96-example curriculum above first; every prompt and LoRA arm below uses that same file.

Before the targeted repair, generate and qualify the target-withheld v0 student. This prevents the experiment from describing an unsafe untuned model as deployed:

```bash
uv sync --extra agent --extra train --extra experiment --extra dev

uv run python -m nightwatch.v0_curriculum_agent \
  --examples-per-label 80 \
  --output artifacts/v0-curriculum.jsonl

uv run modal run src/nightwatch/modal_v0.py \
  --curriculum artifacts/v0-curriculum.jsonl

# Development-only sequence-classifier arm; do not point this at the frozen set.
uv run modal run src/nightwatch/modal_classifier.py \
  --curriculum artifacts/v0-curriculum.jsonl \
  --dev artifacts/v0-dev.jsonl \
  --rank 8 \
  --learning-rate 0.001
```

The Modal run requires a named secret, `nightwatch-huggingface`, containing `HF_TOKEN`. It persists the immutable adapter and report in the `nightwatch-experiment-artifacts` Modal Volume and writes predictions plus the acceptance report locally under `artifacts/`.

```bash
uv sync --extra train --extra dev

uv run python -m nightwatch.predict_gemma \
  --output artifacts/baseline-predictions.jsonl

uv run python -m nightwatch.predict_gemma \
  --few-shot artifacts/generated-curriculum.jsonl \
  --few-shot-count 16 \
  --output artifacts/prompt-practical-predictions.jsonl

uv run python -m nightwatch.predict_gemma \
  --few-shot artifacts/generated-curriculum.jsonl \
  --output artifacts/prompt-matched-predictions.jsonl

uv run python -m nightwatch.train_gemma \
  --curriculum artifacts/generated-curriculum.jsonl \
  --output-dir artifacts/adapter-seed-42 \
  --seed 42

uv run python -m nightwatch.train_gemma \
  --curriculum artifacts/generated-curriculum.jsonl \
  --output-dir artifacts/adapter-seed-31415 \
  --seed 31415

uv run python -m nightwatch.predict_gemma \
  --adapter artifacts/adapter-seed-42 \
  --output artifacts/candidate-seed-42-predictions.jsonl

uv run python -m nightwatch.predict_gemma \
  --adapter artifacts/adapter-seed-31415 \
  --output artifacts/candidate-seed-31415-predictions.jsonl

uv run nightwatch evaluate \
  --eval data/eval/frozen.jsonl \
  --curriculum artifacts/generated-curriculum.jsonl \
  --baseline artifacts/baseline-predictions.jsonl \
  --candidate artifacts/prompt-practical-predictions.jsonl \
  --report artifacts/prompt-practical-report.json

uv run nightwatch evaluate \
  --eval data/eval/frozen.jsonl \
  --curriculum artifacts/generated-curriculum.jsonl \
  --baseline artifacts/baseline-predictions.jsonl \
  --candidate artifacts/prompt-matched-predictions.jsonl \
  --report artifacts/prompt-matched-report.json

uv run nightwatch evaluate \
  --eval data/eval/frozen.jsonl \
  --curriculum artifacts/generated-curriculum.jsonl \
  --baseline artifacts/baseline-predictions.jsonl \
  --candidate artifacts/candidate-seed-42-predictions.jsonl \
  --report artifacts/seed-42-report.json

uv run nightwatch evaluate \
  --eval data/eval/frozen.jsonl \
  --curriculum artifacts/generated-curriculum.jsonl \
  --baseline artifacts/baseline-predictions.jsonl \
  --candidate artifacts/candidate-seed-31415-predictions.jsonl \
  --report artifacts/seed-31415-report.json
```

## What is still deliberately absent

Nightwatch does not yet schedule nightly repair, accept arbitrary model manifests, update a production adapter pointer, or launch training from the public service. Missions are operator-authenticated and restricted to one pinned, budget-capped manifest. A production pointer still requires a separately authorized promoter identity plus rollback tests.

## Spike success and kill criteria

Continue to the full product only if two independent training seeds each achieve at least +20 percentage points on the target suite, zero regression-suite decline, and zero safety-critical misses. Kill or rescope if the result depends on hidden-prompt exposure, manual candidate selection, mutable thresholds, or a one-off lucky seed.

See [the architecture](docs/architecture.md), [feasibility experiment](docs/experiment-plan.md), [threat model](docs/threat-model.md), and [Cloud Run job instructions](cloud/README.md).
