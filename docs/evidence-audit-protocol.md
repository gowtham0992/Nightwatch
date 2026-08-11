# Evidence audit protocol v1

This audit tests whether Nightwatch's retained labels follow the written rubric. It is not a mechanism for making a refused candidate pass.

## Frozen scope

- Audit every row in `artifacts/v0-dev.jsonl` and `data/eval/frozen.jsonl`: 300 cases total.
- Preserve the original files, hashes, reports, predictions, and policy-v1 verdicts permanently.
- Give the machine reviewer only the labeling rubric, a shuffled prompt, and an opaque audit ID.
- Do not expose source file, case ID, suite, original label, safety-critical flag, candidate prediction, confidence, or prior verdict.
- Use `gemini-3.6-flash` for one rubric-only machine pass. This is an advisory reviewer, not final ground truth.
- Require explicit adjudication for every disagreement between the retained label and the machine pass. No dataset is rewritten automatically.
- Apply accepted changes across the complete audited corpus, record a rationale for each change, and write new versioned files with new hashes. Never overwrite v1.
- Re-score each retained prediction file exactly once against the adjudicated v2 evidence. Do not train or tune between audit and re-score.

## Policy v2

Qualification measures fitness to deploy: minimum regression and safety accuracy, minimum non-page regression recalls, zero critical misses, and complete coverage remain unchanged. The target-accuracy ceiling is removed because additional competence is not a deployment failure. Policy v1 remains available for reproducing every retained verdict.

## Decision rule

If adjudication is incomplete, policy-v2 evidence does not exist. If the completed v2 re-score still refuses every candidate, Nightwatch uses the refusal-only demo and performs no further model search. If a candidate passes, it may be described only as certified for deployment under policy v2—not as a repaired model.
