# Nightwatch Evolution

**AI can propose its own upgrade. It cannot approve it.**

Nightwatch is being built as an autonomous release guardian for small production models. Its target workflow uses Gemini agents to diagnose a failing behavior and design a targeted curriculum, a Cloud Run GPU job to fine-tune a Gemma 3 270M LoRA candidate, and frozen code-scored evaluations that promote the candidate only when it improves the target without regression or safety failure.

This project targets **The Taskmaster** track: Nightwatch takes an entire model-repair workflow from observed failure to a promoted or rejected candidate without hand-holding.

![Nightwatch target architecture](docs/images/hb3so.png)

## What works now

The implemented feasibility slice has a frozen incident-triage evaluation, exact-overlap leakage checks, deterministic scoring, a fail-closed promotion gate, a file journal, and a transaction-safe Firestore journal adapter. The adapter passed a live idempotent-write and hash-chain smoke test against Nightwatch's free-tier Firestore database; the temporary contract-test documents were verified deleted afterward. A read-only Flask service can serve the evidence UI and retrieve a bounded, verified mission chain from Firestore. Its production container runs as a non-root user and has passed local health, UI, and mutation-denial smoke tests. The deterministic gate demonstrates two fixture decisions:

- a candidate improving the target from 40% to 80%, with no regression, is promoted;
- a tempting candidate reaching 100% on the target is rejected because it downgrades one obvious production outage.

The checked-in prediction files are **gate fixtures**, not claimed model-training results or autonomous workflow history. The fixture command deliberately does not write lifecycle journal entries. Real Gemma evidence requires the credentialed run below.

## Run the evidence logbook UI

The single-screen UI in `web/` displays one retained Modal v0 run. Before Vite starts or builds, `web/scripts/build-retained-evidence.mjs` regenerates the screen data from the checked-in curriculum, predictions, evaluation set, and report. It does not represent this retained evidence as a live Google Cloud mission.

```bash
cd web
npm install
npm run dev
```

Use `npm run build` for the production bundle. The generated adapter snapshot at `web/src/data/retained-v0.json` is a temporary, content-addressed boundary that will be replaced by verified Firestore mission documents after the Google Cloud deployment exists.

## Run the read-only evidence service

The service exposes `GET /healthz`, `GET /api/missions/<cycle_id>`, and the static evidence UI. It deliberately has no HTTP write or mission-trigger route. Build and run the same container intended for Cloud Run:

```bash
docker build --file containers/service.Dockerfile --tag nightwatch-service:local .
docker run --rm --publish 127.0.0.1:8080:8080 nightwatch-service:local
```

Without Google Application Default Credentials, the UI and shallow health check work locally while Firestore mission reads fail quietly with HTTP 503. A deployed service should receive only Firestore read permission through its service account.

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

## Not implemented yet

The Diagnostician, Cloud Run deployment and orchestration, persistent Firestore mission lifecycle, evaluator/promoter services, production adapter pointer, scheduled nightly runs, and deployed IAM proof are planned architecture—not current evidence. The evidence service exists and passes local container checks, but it is not deployed. Each future service must write its own lifecycle transition when the work actually occurs.

## Spike success and kill criteria

Continue to the full product only if two independent training seeds each achieve at least +20 percentage points on the target suite, zero regression-suite decline, and zero safety-critical misses. Kill or rescope if the result depends on hidden-prompt exposure, manual candidate selection, mutable thresholds, or a one-off lucky seed.

See [the architecture](docs/architecture.md), [feasibility experiment](docs/experiment-plan.md), [threat model](docs/threat-model.md), and [Cloud Run job instructions](cloud/README.md).
