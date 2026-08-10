# Nightwatch Evolution

**AI can propose its own upgrade. It cannot approve it.**

Nightwatch is being built as an autonomous release guardian for small production models. Its target workflow uses Gemini agents to diagnose a failing behavior and design a targeted curriculum, a Cloud Run GPU job to fine-tune a Gemma 3 270M LoRA candidate, and frozen code-scored evaluations that promote the candidate only when it improves the target without regression or safety failure.

This project targets **The Taskmaster** track: Nightwatch takes an entire model-repair workflow from observed failure to a promoted or rejected candidate without hand-holding.

![Nightwatch target architecture](docs/images/hb3so.png)

## What works now

The implemented local feasibility slice has a frozen incident-triage evaluation, exact-overlap leakage checks, deterministic scoring, a fail-closed promotion gate, and a tested hash-chained journal primitive. It demonstrates two fixture decisions:

- a candidate improving the target from 40% to 80%, with no regression, is promoted;
- a tempting candidate reaching 100% on the target is rejected because it downgrades one obvious production outage.

The checked-in prediction files are **gate fixtures**, not claimed model-training results or autonomous workflow history. The fixture command deliberately does not write lifecycle journal entries. Real Gemma evidence requires the credentialed run below.

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

## Run the real Gemma spike

Gemma access requires accepting its Hugging Face terms and providing `HF_TOKEN` through the environment or Secret Manager.

```bash
uv sync --extra train --extra dev

uv run python -m nightwatch.predict_gemma \
  --output artifacts/baseline-predictions.jsonl

uv run python -m nightwatch.train_gemma \
  --curriculum data/curriculum/silent_failure.jsonl \
  --output-dir artifacts/adapter

uv run python -m nightwatch.predict_gemma \
  --adapter artifacts/adapter \
  --output artifacts/candidate-predictions.jsonl

uv run nightwatch gate-fixture \
  --baseline artifacts/baseline-predictions.jsonl \
  --candidate artifacts/candidate-predictions.jsonl \
  --report artifacts/real-report.json
```

## Generate curriculum with Gemini and Google ADK

The curriculum agent receives only an aggregate diagnosis—not hidden eval prompts. Set `GOOGLE_API_KEY` for the Gemini API or configure Vertex AI ADC, then run:

```bash
uv sync --extra agent
uv run python -m nightwatch.curriculum_agent \
  --diagnosis data/diagnosis/silent_failure.json \
  --output artifacts/generated-curriculum.jsonl \
  --examples 32
```

The pinned architect model is `gemini-3.6-flash`; `gemini-3.5-flash` is the fallback if availability requires it.

## Not implemented yet

The Diagnostician, Pub/Sub orchestration, Firestore lifecycle persistence, evaluator/promoter services, production adapter pointer, scheduled nightly runs, and deployed IAM proof are planned architecture—not current evidence. Each future service must write its own lifecycle transition when the work actually occurs.

## Spike success and kill criteria

Continue to the full product only if two independent training seeds each achieve at least +20 percentage points on the target suite, zero regression-suite decline, and zero safety-critical misses. Kill or rescope if the result depends on hidden-prompt exposure, manual candidate selection, mutable thresholds, or a one-off lucky seed.

See [the architecture](docs/architecture.md), [feasibility experiment](docs/experiment-plan.md), [threat model](docs/threat-model.md), and [Cloud Run job instructions](cloud/README.md).
