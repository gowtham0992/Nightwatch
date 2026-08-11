# Gemma feasibility experiment

This experiment decides whether Nightwatch remains a model-repair product or is rescoped around governed release decisions. It must run before the event-driven cloud spine is built.

## Deployable v0 prerequisite

The untuned Gemma model is not the repair baseline: it misses every frozen safety-critical case and would not be credible as a deployed model. Before the targeted repair, train one v0 adapter on 240 general-triage examples with the silent-downstream-stall behavior explicitly withheld.

The v0 curriculum must contain 80 examples per label, use only the code-owned category taxonomy, contain no exact frozen-eval overlap, and report lexical near-duplicate advisories. Accept v0 only when it has complete predictions, zero safety-critical misses, at least 80% regression accuracy, at least 90% safety accuracy, at least 70% regression recall for both `defer` and `investigate`, and no more than 60% target accuracy. These thresholds make v0 plausibly deployable while preserving a measurable target blind spot. If v0 fails, revise only the general curriculum or training recipe; do not interpret a targeted-repair result against an unqualified baseline.

## Frozen evidence

The frozen set contains 150 independently worded incident-triage cases and is separate from the 11-case gate fixture:

- approximately 40 target silent-failure cases;
- approximately 80 regression cases spanning benign, investigate, and ordinary page-now incidents;
- approximately 30 safety cases, with at least 10 marked critical.

Labels follow the committed [incident-triage rubric](../data/eval/LABELING.md). Current frozen-set SHA-256: `751a639716d3ad0d62ad3bb65924e7dfcaf019afab2894d12e821fe93a3bc0ac`.

The base model is pinned to Hugging Face commit `ac82b4e820549b854eebf28ce6dedaf9fdfa17b3`; reports must record this revision rather than relying on a mutable model name.

Store the dataset SHA-256 in every report. Exact canonical prompt overlap is blocked. Token-Jaccard matches at or above 0.5 are reported as advisories, and the maximum observed score is always included even when it falls below that threshold. This lexical check is not represented as proof that semantic leakage is impossible.

## Compared systems

Evaluate the same frozen cases with deterministic decoding against:

1. Untuned `google/gemma-3-270m-it` as a diagnostic control, not the deployed baseline.
2. Qualified target-withheld v0 adapter as the deployed repair baseline.
3. Practical prompt-only Gemma with 16 examples, selected label-stratified from the first generated examples with no manual replacement.
4. Matched-count prompt-only Gemma using the full 64–128-example curriculum supplied to LoRA, in original generation order.
5. LoRA repair candidate starting from the qualified v0 adapter, seed 42.
6. LoRA repair candidate starting from the same qualified v0 adapter, seed 31415.
7. A third predeclared seed only if the first two disagree materially; never replace a bad seed silently.

The matched-count arm is the scientific control. The 16-example arm represents the recurring serving-cost tradeoff of carrying many demonstrations in every inference request.

Report each run separately. Do not select the best seed as the headline result.

## Curriculum budget

Use 64–128 examples per cycle, including negative examples adjacent to the target behavior. The Curriculum Architect receives an aggregate taxonomy only. It never receives raw frozen prompts.

## Metrics

- accuracy for target, regression, and safety suites;
- target gain versus the qualified v0 baseline;
- regression drop versus the qualified v0 baseline;
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

## Development-set status

These are model-selection results on the independent development set, not frozen-test claims. The frozen set remains unopened for model selection.

The first generative v0 adapter failed because it never emitted `defer`. A sequence-classification adapter at the original `5e-5` learning rate also underfit, reaching 28% development accuracy and 0.229 macro-F1. An explicit trainability audit now requires both LoRA weights and the `score` head to be trainable and serialized.

The next audit found a curriculum artifact: every `defer` example began with `ALERT:` or `INFO:`, while every other label used plain text. Label-independent prefix normalization removed that shortcut. With the corrected pipeline and a `1e-3` learning rate:

- rank 4 reached 77.5% regression accuracy, 80.0% safety accuracy, 53.6% regression `defer` recall, zero critical misses, and 42.5% target accuracy;
- rank 8 reached 83.75% regression accuracy, 83.3% safety accuracy, 75% regression `defer` recall, one critical miss, and 40% target accuracy.

Neither adapter qualifies as v0. Rank 8 shows that 270M capacity can satisfy the ordinary-triage and withheld-target constraints, but safety remains below policy. Do not tune against individual development prompts. The next permitted intervention is independently generated safety hard negatives with teacher rationales, followed by one retained rerun. If that still misses safety, move the student to the next Gemma size instead of weakening the gate.

That intervention is fixed before generation: 24 explicit `page_now` safety cases across confirmed corruption, compromise, total outage, and severe customer harm; four ambiguous `investigate` cases; and four verified-resolved/test-only `defer` cases. Gemini receives only this plan and the withheld-behavior rule. Deterministic post-generation checks reject wrong counts, missing rationales, canonical duplicates, exact overlap, or token Jaccard similarity of 0.50 or greater against either development or frozen evidence. The retained rerun uses rank 8, three epochs, learning rate `1e-3`, and seed `20260809`; no configuration search follows it.

The fixed augmentation was generated by `gemini-3.6-flash`, producing 32 accepted rows with maximum token Jaccard 0.25 against development and 0.222222 against frozen evidence. The retained Modal run `ap-TxOPqk13zK4ldC98hLT9HW` removed the previous critical miss and passed the regression, non-page recall, target-ceiling, coverage, and zero-critical-miss invariants. It was still **refused** because safety remained 25/30 (83.3%) against the fixed 90% threshold. Per the predeclared decision, no additional 270M configuration search is permitted; the next student experiment moves to the next Gemma size without changing the gate.

The capacity test is pinned to `google/gemma-3-1b-it` revision `dcc83ea841ab6100d6b47a070329e1ba4cf78752`, using the same safety-augmented curriculum, development evidence, rank 8, three epochs, learning rate `1e-3`, and seed `20260809`. Model ID and immutable revision are part of the artifact identity. No 1B hyperparameter search is permitted before this result is interpreted.
