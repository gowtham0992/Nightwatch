# Scam-safety baseline record

Nightwatch's first retained scam-safety baseline is
`scam-v0-de1e6009-2d77e636-c0e947096d`. It is a LoRA sequence classifier on
the pinned `google/gemma-3-1b-it` revision in the mission contract. Gemini 3.6
Flash authored the original bounded curriculum and development evidence through
Google ADK; Modal trained the student on an L4 GPU.

## Reproducible result

The in-memory Trainer evaluation and a clean reload of the saved adapter both
produced exactly the same result:

- overall accuracy: 70/80 (87.5%);
- macro-F1: 0.8233;
- target: 22/24 (91.7%);
- regression: 25/32 (78.1%);
- safety: 23/24 (95.8%);
- safety-critical misses: 0;
- benign messages incorrectly blocked: 0/14.

A second independent Modal reload produced byte-identical predictions. The
retained prediction SHA-256 is
`995e74b823ee1259652d74b7de108832a665f3ec28635c822efdf2bed3353884`.

## Why an earlier run is not the baseline

An earlier diagnostic run appeared to score 77.5% inside Trainer and 90.0%
after reload. Nightwatch did not accept either headline. Reproduction showed
that Gemma 3 BF16 sequence-classification outputs changed with padded batch
composition: batch size 16 collapsed twelve distinct examples toward the same
class, while padding-free single-example evaluation did not.

Pipeline version 2 therefore makes single-example evaluation part of the
artifact identity and uses it for both checkpoint selection and retained
inference. The corrected run made Trainer and clean-reload metrics identical.
The earlier artifact remains diagnostic evidence only and must not be presented
as a product result.

## Observed repair opportunity

The corrected baseline retained ten development errors. Gemini's bounded
diagnostician cited three of them as one coherent failure pattern: plausible
delivery and file-notification framing can cause the model to underweight an
unverified external link or an explicit credential request. The repair plan
selects three fixed curriculum families with 16 examples each and protects
benign workplace messages and legitimate official-channel notices.

The repair plan cannot change the task labels, release gate, source evidence,
or sealed evaluation. Its SHA-256 is
`aedaf3b021d73ed62680d2a597fd7f510a80c98aeb9f6a7f617e5d3f38e18f2b`.

## Retained local evidence

- `artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-development-report.json`
- `artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-development-predictions.jsonl`
- `artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-reevaluation-report.json`
- `artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-repair-plan.json`

The corrected training run is visible in Modal as
`ap-QbfjDdAX1bz26C7j4gH2KE`; the independent reload is
`ap-YhswEn1wbUntbW4QROBsd2`.
