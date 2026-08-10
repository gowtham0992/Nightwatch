from __future__ import annotations

import argparse
import json
from pathlib import Path

from nightwatch.datasets import (
    assert_no_eval_leakage,
    dataset_sha256,
    find_near_duplicate_prompts,
    load_curriculum,
    load_eval_cases,
    load_predictions,
)
from nightwatch.evaluation import evaluate
from nightwatch.gate import decide


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_gate_fixture(args: argparse.Namespace) -> int:
    cases = load_eval_cases(args.eval)
    curriculum = load_curriculum(args.curriculum)
    assert_no_eval_leakage(curriculum, cases)
    near_duplicate_threshold = 0.75
    near_duplicates = find_near_duplicate_prompts(
        curriculum,
        cases,
        threshold=near_duplicate_threshold,
    )
    baseline = evaluate("gemma-3-270m-it:baseline", cases, load_predictions(args.baseline))
    candidate = evaluate(args.candidate.stem, cases, load_predictions(args.candidate))
    result = decide(baseline, candidate)
    report = {
        "evidence": {
            "eval_sha256": dataset_sha256(args.eval),
            "curriculum_sha256": dataset_sha256(args.curriculum),
            "near_duplicate_threshold": near_duplicate_threshold,
            "near_duplicate_advisories": [item.to_dict() for item in near_duplicates],
        },
        "baseline": baseline.to_dict(),
        "candidate": candidate.to_dict(),
        "gate": result.to_dict(),
    }
    _write_json(args.report, report)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nightwatch deterministic evolution gate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    fixture = subparsers.add_parser(
        "gate-fixture",
        help="score checked-in prediction fixtures; does not claim or journal an autonomous lifecycle",
    )
    fixture.add_argument("--eval", type=Path, default=Path("data/eval/fixture.jsonl"))
    fixture.add_argument("--curriculum", type=Path, default=Path("data/curriculum/silent_failure.jsonl"))
    fixture.add_argument("--baseline", type=Path, default=Path("data/predictions/baseline.jsonl"))
    fixture.add_argument("--candidate", type=Path, default=Path("data/predictions/good_candidate.jsonl"))
    fixture.add_argument("--report", type=Path, default=Path("artifacts/report.json"))
    fixture.set_defaults(func=run_gate_fixture)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
