# Gemma feasibility experiment

This experiment decides whether Nightwatch remains a model-repair product or is rescoped around governed release decisions. It must run before the event-driven cloud spine is built.

## Frozen evidence

Create and commit at least 150 independently worded incident-triage cases before generating curriculum:

- approximately 40 target silent-failure cases;
- approximately 80 regression cases spanning benign, investigate, and ordinary page-now incidents;
- approximately 30 safety cases, with at least 10 marked critical.

Store the dataset SHA-256 in every report. Exact canonical prompt overlap is blocked. Token-Jaccard near-duplicate scores are reported as an advisory; they are not represented as proof that semantic leakage is impossible.

## Compared systems

Evaluate the same frozen cases with deterministic decoding against:

1. Untuned `google/gemma-3-270m-it`.
2. Prompt-only Gemma using the diagnosis and matched few-shot examples, with no weight update.
3. LoRA candidate, seed 42.
4. LoRA candidate, seed 31415.
5. A third predeclared seed only if the first two disagree materially; never replace a bad seed silently.

Report each run separately. Do not select the best seed as the headline result.

## Curriculum budget

Use 64–128 examples per cycle, including negative examples adjacent to the target behavior. The Curriculum Architect receives an aggregate taxonomy only. It never receives raw frozen prompts.

## Metrics

- accuracy for target, regression, and safety suites;
- target gain versus untuned baseline;
- regression drop versus untuned baseline;
- safety-critical miss IDs;
- invalid or missing predictions;
- LoRA improvement over the prompt-only comparison;
- wall-clock training time and estimated Cloud Run cost.

## Predeclared decisions

- **Continue:** both LoRA seeds gain at least 20 percentage points on target, neither loses regression accuracy, and neither has a critical miss.
- **Iterate curriculum:** at most three total curriculum iterations, with every attempt retained in the journal.
- **Rescope gate-first:** LoRA passes safety but beats prompt-only by less than 10 percentage points.
- **Kill the repair claim:** both seeds remain below +20 points after three curricula, any result depends on removing a bad seed, or improvement requires leaked/near-duplicate prompts.

The checked-in 11-case fixture is only a gate test and must never appear as scientific evidence in the submission.
