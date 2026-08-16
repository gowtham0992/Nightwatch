# Scam-safety decision evidence

This directory retains the minimum evidence needed to recompute the six candidate decisions shown in the Nightwatch product. Generated checkpoints and adapters remain excluded because they are large, access-controlled training outputs; the committed prediction rows, gate records, source data, and hashes are sufficient to reproduce each deterministic release decision without Gemini, Modal, or Google Cloud credentials.

## Evidence boundary

Every retained gate binds four inputs by SHA-256:

- `data/scam_safety/mission.json`, the versioned release policy;
- `data/scam_safety/development-v1.jsonl`, the 92-case evaluation input;
- the full-coverage retained baseline predictions in this directory;
- the candidate prediction file named below.

The archive intentionally keeps the six decisions exposed by `web/src/data/scamMission.js`:

| UI attempt | Archived gate | Candidate predictions | Decision |
|---|---|---|---|
| v1 | `scam-candidate-v1-d0ab5041-ffca8c22-838eb5ca96-gate.json` | `scam-candidate-v1-d0ab5041-ffca8c22-838eb5ca96-reevaluation-predictions.jsonl` | refused |
| v2 | `scam-candidate-v2-2b769143-ffca8c22-0d858e40da-gate.json` | `scam-candidate-v2-2b769143-ffca8c22-0d858e40da-reevaluation-predictions.jsonl` | refused |
| v3 | `scam-candidate-v3-ebd8e944-ffca8c22-ae20b3fe51-gate.json` | `scam-candidate-v3-ebd8e944-ffca8c22-ae20b3fe51-reevaluation-predictions.jsonl` | refused |
| v5 | `scam-candidate-v5-ebd8e944-ffca8c22-2f98bfc17f-gate.json` | `scam-candidate-v6-ebd8e944-ffca8c22-49b834a25c-development-predictions.jsonl` | refused |
| v7 | `scam-candidate-v7-0f932496-ffca8c22-349438eaa4-gate.json` | `scam-candidate-v7-0f932496-ffca8c22-349438eaa4-development-predictions.jsonl` | refused |
| v8 | `scam-candidate-v8-fd2b06dd-ffca8c22-7e228df886-gate.json` | `scam-candidate-v8-fd2b06dd-ffca8c22-7e228df886-reevaluation-predictions.jsonl` | qualified, not deployed |

The v5 gate is bound to the prediction bytes later retained under the v6 filename. The gate's `candidate_id` remains v5, and its `source_hashes.candidate_predictions_sha256` resolves to those exact bytes. The archive preserves that historical naming rather than renaming evidence after evaluation.

Run the focused evidence test to recompute all six records and compare the complete baseline, candidate, hashes, and decision payloads:

```bash
UV_CACHE_DIR=/tmp/nightwatch-uv-cache uv run pytest tests/test_scam_evidence_archive.py -q
```

## Fresh cycle and retained candidate identities

The retained v8 candidate is `scam-candidate-v8-fd2b06dd-ffca8c22-7e228df886`. The later Google Cloud mission `nightwatch-scam-20260814-001` produced the cycle-bound identity `scam-candidate-v8-fd2b06dd-ffca8c22-798e69378e`.

Those names do not claim byte-identical adapters. The fresh mission's recorded prediction SHA-256 is `1ec3a48de5a9b0dbbd59feb84723536af1919899888a70d4fd9522dbc9605777`; the committed retained v8 prediction file hashes to that same value. The evidence therefore establishes identical outputs on the sealed 92-case suite, while the adapter objects remain separate cycle-bound training artifacts.

## Baseline versions

The original retained baseline report covers 80 cases. The later full-coverage baseline file covers `development-v1.jsonl`, which contains 92 cases, and scores 30/36 on its expanded target partition with no invalid case IDs. The public refusal mission retained an earlier live input for the expanded suite, scores 23/36 on target, and records 24 mismatched case identities. It was still refused on a separate protected invariant: routine-message recall declined from 87.5% to 75.0%.

The archive does not rewrite either mission to make the baselines appear identical. Use comparisons within one gate record; do not compare 63.9% and 83.3% as repeated measurements of the same exact evidence input.
