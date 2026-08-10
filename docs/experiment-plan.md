# Gemma feasibility experiment

This experiment decides whether Nightwatch remains a model-repair product or is rescoped around governed release decisions. It must run before the event-driven cloud spine is built.

## Frozen evidence

The frozen set contains 150 independently worded incident-triage cases and is separate from the 11-case gate fixture:

- approximately 40 target silent-failure cases;
- approximately 80 regression cases spanning benign, investigate, and ordinary page-now incidents;
- approximately 30 safety cases, with at least 10 marked critical.

Labels follow the committed [incident-triage rubric](../data/eval/LABELING.md). Current frozen-set SHA-256: `751a639716d3ad0d62ad3bb65924e7dfcaf019afab2894d12e821fe93a3bc0ac`.

Store the dataset SHA-256 in every report. Exact canonical prompt overlap is blocked. Token-Jaccard matches at or above 0.5 are reported as advisories, and the maximum observed score is always included even when it falls below that threshold. This lexical check is not represented as proof that semantic leakage is impossible.

## Compared systems

Evaluate the same frozen cases with deterministic decoding against:

1. Untuned `google/gemma-3-270m-it`.
2. Practical prompt-only Gemma with 16 examples, selected label-stratified from the first generated examples with no manual replacement.
3. Matched-count prompt-only Gemma using the full 64–128-example curriculum supplied to LoRA, in original generation order.
4. LoRA candidate, seed 42.
5. LoRA candidate, seed 31415.
6. A third predeclared seed only if the first two disagree materially; never replace a bad seed silently.

The matched-count arm is the scientific control. The 16-example arm represents the recurring serving-cost tradeoff of carrying many demonstrations in every inference request.

Report each run separately. Do not select the best seed as the headline result.

## Curriculum budget

Use 64–128 examples per cycle, including negative examples adjacent to the target behavior. The Curriculum Architect receives an aggregate taxonomy only. It never receives raw frozen prompts.

## Metrics

- accuracy for target, regression, and safety suites;
- target gain versus untuned baseline;
- regression drop versus untuned baseline;
- regression recall for `defer` and `investigate`, each with a 50% absolute floor and zero decline versus baseline;
- regression false-page rate: `page_now` predictions whose expected label is `defer` or `investigate`;
- safety-critical miss IDs;
- invalid or missing predictions;
- LoRA improvement over the prompt-only comparison;
- wall-clock training time and estimated Cloud Run cost.

## Predeclared decisions

- **Continue:** both LoRA seeds gain at least 20 percentage points on target; neither loses regression accuracy, `defer` recall, or `investigate` recall; both non-page recalls remain at least 50%; and neither seed has a critical miss.
- **Gate sanity:** all three constant policies (`always_page_now`, `always_investigate`, and `always_defer`) must be rejected against the measured baseline before training results are interpreted.
- **Iterate curriculum:** at most three total curriculum iterations, with every attempt retained in the journal.
- **Rescope gate-first:** LoRA passes safety but beats prompt-only by less than 10 percentage points.
- **Kill the repair claim:** both seeds remain below +20 points after three curricula, any result depends on removing a bad seed, or improvement requires leaked/near-duplicate prompts.

The checked-in 11-case fixture is only a gate test and must never appear as scientific evidence in the submission.
