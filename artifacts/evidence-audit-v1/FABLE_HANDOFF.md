# Independent evidence adjudication for Nightwatch

Decide all 44 disputed incident labels from the written rubric alone. This is an evidence-quality review, not an attempt to make a model pass qualification.

## Read only these files

1. `data/eval/LABELING.md`
2. `docs/evidence-audit-protocol.md`
3. `artifacts/evidence-audit-v1/adjudication-packet.jsonl`

Do not inspect model predictions, evaluation reports, qualification verdicts, training runs, candidate identities, or gate thresholds. If any of that information is already in your context, explicitly ignore it. Do not modify the original development or frozen evidence files.

## Make one explicit decision per row

For every row in `adjudication-packet.jsonl`:

- Read the incident `prompt` literally against `LABELING.md`.
- Choose exactly one `adjudicated_label`: `page_now`, `investigate`, or `defer`. You may choose a third label when both the retained and machine labels are wrong.
- Write a concrete `adjudicator_rationale` explaining which prompt evidence and rubric rule control the decision. Do not mention candidate performance or the effect the decision could have on a verdict.
- Set `adjudicator` to `claude-fable`.
- Set `adjudication_status` to `resolved`.
- Preserve every other field verbatim, including order and `audit_id`.

When a prompt is genuinely underspecified, apply the rubric's most conservative literal reading and say what missing fact prevents a stronger label. Do not repair an ambiguous prompt by inventing production impact.

## Output contract

Write exactly 44 JSON Lines rows to:

`artifacts/evidence-audit-v1/adjudication-decisions.jsonl`

The output must retain exact audit-ID coverage with no duplicates. After the JSONL file, report only:

- counts by adjudicated label;
- counts of retained labels upheld versus changed;
- any recurring rubric ambiguity that should be fixed in a future evidence version.

Do not create v2 datasets, rescore candidates, retrain a model, or recommend a winner. Nightwatch performs those steps only after validating the completed decision file.
