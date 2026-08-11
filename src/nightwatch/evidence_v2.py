from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from nightwatch.datasets import ALLOWED_LABELS, load_eval_cases, load_predictions
from nightwatch.evaluation import evaluate
from nightwatch.v0 import V0_POLICY_V2, assess_v0

ADJUDICATION_FIELDS = frozenset(
    {
        "adjudicated_label",
        "adjudicator_rationale",
        "adjudicator",
        "adjudication_status",
    }
)

RETAINED_PREDICTIONS = (
    {
        "evidence_source": "frozen",
        "predictions": Path("artifacts/v0-18a33dfd5c54-seed-20260809-predictions.jsonl"),
        "original_report": Path("artifacts/v0-18a33dfd5c54-seed-20260809-report.json"),
    },
    {
        "evidence_source": "development",
        "predictions": Path(
            "artifacts/classifier-1395040c-1e98fdcf-74d932a468-dev-predictions.jsonl"
        ),
        "original_report": Path(
            "artifacts/classifier-1395040c-1e98fdcf-74d932a468-dev-report.json"
        ),
    },
    {
        "evidence_source": "development",
        "predictions": Path(
            "artifacts/classifier-1395040c-1e98fdcf-2f16394da7-dev-predictions.jsonl"
        ),
        "original_report": Path(
            "artifacts/classifier-1395040c-1e98fdcf-2f16394da7-dev-report.json"
        ),
    },
)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_number}: row must be an object")
        rows.append(row)
    if not rows:
        raise ValueError(f"{path}: no rows")
    return rows


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_adjudication_decisions(
    packet: list[dict[str, object]],
    decisions: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    if not packet:
        raise ValueError("adjudication packet is empty")
    packet_ids = [row.get("audit_id") for row in packet]
    decision_ids = [row.get("audit_id") for row in decisions]
    if (
        len(decisions) != len(packet)
        or len(set(decision_ids)) != len(decision_ids)
        or decision_ids != packet_ids
    ):
        raise ValueError("adjudication coverage or row order does not match the frozen packet")

    validated: dict[str, dict[str, object]] = {}
    for index, (original, decision) in enumerate(zip(packet, decisions, strict=True), start=1):
        audit_id = original.get("audit_id")
        if not isinstance(audit_id, str):
            raise ValueError(f"adjudication packet row {index}: audit_id must be a string")
        if set(original) != set(decision):
            raise ValueError(f"adjudication row {audit_id}: context drift in field set")
        original_context = {
            key: value for key, value in original.items() if key not in ADJUDICATION_FIELDS
        }
        decision_context = {
            key: value for key, value in decision.items() if key not in ADJUDICATION_FIELDS
        }
        if decision_context != original_context:
            raise ValueError(f"adjudication row {audit_id}: context drift")
        if decision.get("adjudication_status") != "resolved":
            raise ValueError(f"adjudication row {audit_id}: status must be resolved")
        label = decision.get("adjudicated_label")
        if label not in ALLOWED_LABELS:
            raise ValueError(f"adjudication row {audit_id}: unsupported label {label!r}")
        adjudicator = decision.get("adjudicator")
        if not isinstance(adjudicator, str) or not adjudicator.strip():
            raise ValueError(f"adjudication row {audit_id}: adjudicator must be named")
        rationale = decision.get("adjudicator_rationale")
        if not isinstance(rationale, str) or not 20 <= len(rationale.strip()) <= 2_000:
            raise ValueError(
                f"adjudication row {audit_id}: rationale must contain 20 to 2,000 characters"
            )
        validated[audit_id] = dict(decision)
    return validated


def apply_adjudicated_labels(
    sources: dict[str, list[dict[str, object]]],
    mapping: list[dict[str, object]],
    decisions: dict[str, dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    source_rows = {
        (source, row.get("id")): row
        for source, rows in sources.items()
        for row in rows
    }
    if len(source_rows) != sum(len(rows) for rows in sources.values()):
        raise ValueError("source evidence contains duplicate source/case IDs")
    mapping_by_source_case: dict[tuple[object, object], dict[str, object]] = {}
    mapping_by_audit_id: dict[object, dict[str, object]] = {}
    for row in mapping:
        source_case = (row.get("source"), row.get("case_id"))
        audit_id = row.get("audit_id")
        if source_case in mapping_by_source_case or audit_id in mapping_by_audit_id:
            raise ValueError("private mapping contains duplicate source/case or audit IDs")
        mapping_by_source_case[source_case] = row
        mapping_by_audit_id[audit_id] = row
    if set(mapping_by_source_case) != set(source_rows):
        raise ValueError("private mapping coverage does not match source evidence")
    if not set(decisions).issubset(mapping_by_audit_id):
        raise ValueError("adjudication decisions contain an audit ID absent from private mapping")

    released: dict[str, list[dict[str, object]]] = {}
    consumed_decisions: set[str] = set()
    for source, rows in sources.items():
        released_rows: list[dict[str, object]] = []
        for index, original in enumerate(rows, start=1):
            case_id = original.get("id")
            mapped = mapping_by_source_case[(source, case_id)]
            for evidence_field, mapping_field in [
                ("suite", "original_suite"),
                ("expected_label", "original_label"),
                ("safety_critical", "safety_critical"),
            ]:
                if original.get(evidence_field, False) != mapped.get(mapping_field, False):
                    raise ValueError(
                        f"{source} row {index}: private mapping drift in {evidence_field}"
                    )
            audit_id = mapped.get("audit_id")
            final_label = original.get("expected_label")
            if audit_id in decisions:
                decision = decisions[str(audit_id)]
                if decision.get("retained_label") != final_label:
                    raise ValueError(f"{source} row {index}: retained label drift")
                final_label = decision["adjudicated_label"]
                consumed_decisions.add(str(audit_id))
            changed = dict(original)
            changed["expected_label"] = final_label
            if any(
                changed.get(key) != value
                for key, value in original.items()
                if key != "expected_label"
            ):
                raise AssertionError("v2 evidence changed a field other than expected_label")
            released_rows.append(changed)
        released[source] = released_rows
    if consumed_decisions != set(decisions):
        raise ValueError("not every adjudication decision was applied exactly once")
    return released


def release_v2(
    *,
    packet_path: Path,
    decisions_path: Path,
    mapping_path: Path,
    development_path: Path,
    frozen_path: Path,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite existing v2 release: {output_dir}")

    packet = _read_jsonl(packet_path)
    decisions_rows = _read_jsonl(decisions_path)
    decisions = validate_adjudication_decisions(packet, decisions_rows)
    mapping = _read_jsonl(mapping_path)
    source_paths = {"development": development_path, "frozen": frozen_path}
    sources = {name: _read_jsonl(path) for name, path in source_paths.items()}
    released = apply_adjudicated_labels(sources, mapping, decisions)

    output_dir.mkdir(parents=True, exist_ok=False)
    evidence_paths = {
        source: output_dir / f"{source}.jsonl" for source in sorted(released)
    }
    for source, path in evidence_paths.items():
        _write_jsonl(path, released[source])
        load_eval_cases(path)

    reports_dir = output_dir / "reports"
    reports_dir.mkdir()
    rescored: list[dict[str, object]] = []
    for retained in RETAINED_PREDICTIONS:
        evidence_source = str(retained["evidence_source"])
        prediction_path = Path(retained["predictions"])
        original_report_path = Path(retained["original_report"])
        original_report = json.loads(original_report_path.read_text(encoding="utf-8"))
        if not isinstance(original_report, dict):
            raise ValueError(f"{original_report_path}: report must be an object")
        artifact_name = original_report.get("artifact_name")
        if not isinstance(artifact_name, str) or not artifact_name:
            raise ValueError(f"{original_report_path}: missing artifact_name")
        expected_v1_hash = original_report.get("dev_sha256", original_report.get("eval_sha256"))
        if expected_v1_hash != _sha256(source_paths[evidence_source]):
            raise ValueError(f"{original_report_path}: original evidence hash mismatch")
        report = evaluate(
            artifact_name,
            load_eval_cases(evidence_paths[evidence_source]),
            load_predictions(prediction_path),
        )
        assessment = assess_v0(report, policy=V0_POLICY_V2)
        rescore = {
            "artifact_name": artifact_name,
            "evidence_source": evidence_source,
            "policy": "v2",
            "rescore_only": True,
            "prediction_path": str(prediction_path),
            "prediction_sha256": _sha256(prediction_path),
            "original_report_path": str(original_report_path),
            "original_report_sha256": _sha256(original_report_path),
            "v1_evidence_sha256": _sha256(source_paths[evidence_source]),
            "v2_evidence_sha256": _sha256(evidence_paths[evidence_source]),
            "evaluation": report.to_dict(),
            "assessment": assessment.to_dict(),
        }
        report_path = reports_dir / f"{prediction_path.stem}-v2-report.json"
        report_path.write_text(json.dumps(rescore, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        rescored.append({**rescore, "report_path": str(report_path)})

    changes = [
        decision
        for decision in decisions.values()
        if decision["adjudicated_label"] != decision["retained_label"]
    ]
    transitions = Counter(
        (str(row["retained_label"]), str(row["adjudicated_label"])) for row in changes
    )
    manifest = {
        "evidence_version": "v2",
        "adjudication_complete": True,
        "rescore_only": True,
        "inputs": {
            "packet_sha256": _sha256(packet_path),
            "decisions_sha256": _sha256(decisions_path),
            "mapping_sha256": _sha256(mapping_path),
            **{
                f"{source}_v1_sha256": _sha256(path)
                for source, path in source_paths.items()
            },
        },
        "outputs": {
            f"{source}_v2_sha256": _sha256(path)
            for source, path in evidence_paths.items()
        },
        "case_count": sum(len(rows) for rows in released.values()),
        "adjudicated_disagreement_count": len(decisions),
        "retained_labels_upheld": len(decisions) - len(changes),
        "retained_labels_changed": len(changes),
        "label_transitions": {
            f"{old}->{new}": count for (old, new), count in sorted(transitions.items())
        },
        "candidate_rescores": [
            {
                "artifact_name": row["artifact_name"],
                "evidence_source": row["evidence_source"],
                "accepted": row["assessment"]["accepted"],
                "reasons": row["assessment"]["reasons"],
                "report_path": row["report_path"],
            }
            for row in rescored
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Release adjudicated v2 evidence and rescore retained predictions")
    parser.add_argument(
        "--packet",
        type=Path,
        default=Path("artifacts/evidence-audit-v1/adjudication-packet.jsonl"),
    )
    parser.add_argument(
        "--decisions",
        type=Path,
        default=Path("artifacts/evidence-audit-v1/adjudication-decisions.jsonl"),
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("artifacts/evidence-audit-v1/private-mapping.jsonl"),
    )
    parser.add_argument("--development", type=Path, default=Path("artifacts/v0-dev.jsonl"))
    parser.add_argument("--frozen", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence-audit-v2"),
    )
    args = parser.parse_args()
    manifest = release_v2(
        packet_path=args.packet,
        decisions_path=args.decisions,
        mapping_path=args.mapping,
        development_path=args.development,
        frozen_path=args.frozen,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
