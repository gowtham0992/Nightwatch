from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from nightwatch.contracts import Prediction
from nightwatch.scam_repair_agent import _prediction_rows
from nightwatch.scam_safety import (
    decide_scam_release,
    evaluate_scam_safety,
    load_scam_eval_cases,
    load_scam_mission,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _predictions(path: Path) -> list[Prediction]:
    return [
        Prediction(case_id=str(row["id"]), label=str(row["label"]))
        for row in _prediction_rows(path)
    ]


def build_scam_gate_record(
    mission_path: Path,
    development_path: Path,
    baseline_predictions_path: Path,
    candidate_predictions_path: Path,
    *,
    baseline_id: str,
    candidate_id: str,
) -> dict[str, object]:
    mission = load_scam_mission(mission_path)
    cases = load_scam_eval_cases(development_path)
    baseline = evaluate_scam_safety(
        baseline_id,
        cases,
        _predictions(baseline_predictions_path),
    )
    candidate = evaluate_scam_safety(
        candidate_id,
        cases,
        _predictions(candidate_predictions_path),
    )
    decision = decide_scam_release(baseline, candidate, mission.gate_policy)
    return {
        "schema_version": 1,
        "mission_id": mission.mission_id,
        "baseline_id": baseline_id,
        "candidate_id": candidate_id,
        "source_hashes": {
            "mission_sha256": _sha256(mission_path),
            "development_sha256": _sha256(development_path),
            "baseline_predictions_sha256": _sha256(baseline_predictions_path),
            "candidate_predictions_sha256": _sha256(candidate_predictions_path),
        },
        "baseline": baseline.to_dict(),
        "candidate": candidate.to_dict(),
        "decision": decision.to_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the deterministic Nightwatch scam gate")
    parser.add_argument("--mission", type=Path, default=Path("data/scam_safety/mission.json"))
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--baseline-predictions", type=Path, required=True)
    parser.add_argument("--candidate-predictions", type=Path, required=True)
    parser.add_argument("--baseline-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite immutable gate record: {args.output}")
    record = build_scam_gate_record(
        args.mission,
        args.development,
        args.baseline_predictions,
        args.candidate_predictions,
        baseline_id=args.baseline_id,
        candidate_id=args.candidate_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "decision": record["decision"]}, indent=2))


if __name__ == "__main__":
    main()
