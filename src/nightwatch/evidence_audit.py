from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from nightwatch.contracts import EvalCase
from nightwatch.datasets import ALLOWED_LABELS, dataset_sha256, load_eval_cases

AUDIT_VERSION = "evidence-audit-v1"


@dataclass(frozen=True)
class BlindAudit:
    packet: tuple[dict[str, str], ...]
    mapping: tuple[dict[str, object], ...]


def _audit_id(source: str, case_id: str) -> str:
    value = f"{AUDIT_VERSION}:{source}:{case_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:20]


def _order_key(row: dict[str, str]) -> str:
    value = f"{AUDIT_VERSION}:shuffle:{row['audit_id']}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def build_blind_audit(sources: Mapping[str, Iterable[EvalCase]]) -> BlindAudit:
    if not sources:
        raise ValueError("audit requires at least one evidence source")
    packet: list[dict[str, str]] = []
    mapping: list[dict[str, object]] = []
    seen_audit_ids: set[str] = set()
    seen_source_cases: set[tuple[str, str]] = set()
    for source in sorted(sources):
        cases = sorted(sources[source], key=lambda case: case.case_id)
        if not cases:
            raise ValueError(f"audit source {source!r} is empty")
        for case in cases:
            source_case = (source, case.case_id)
            if source_case in seen_source_cases:
                raise ValueError(f"duplicate source case in audit: {source}/{case.case_id}")
            seen_source_cases.add(source_case)
            opaque_id = _audit_id(source, case.case_id)
            if opaque_id in seen_audit_ids:
                raise ValueError("audit ID collision")
            seen_audit_ids.add(opaque_id)
            packet.append({"audit_id": opaque_id, "prompt": case.prompt})
            mapping.append(
                {
                    "audit_id": opaque_id,
                    "source": source,
                    "case_id": case.case_id,
                    "original_suite": case.suite.value,
                    "original_label": case.expected_label,
                    "safety_critical": case.safety_critical,
                }
            )
    packet.sort(key=_order_key)
    mapping.sort(key=lambda row: str(row["audit_id"]))
    return BlindAudit(tuple(packet), tuple(mapping))


def reconcile_machine_judgments(
    audit: BlindAudit,
    judgments: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    expected_ids = {row["audit_id"] for row in audit.mapping}
    by_id: dict[str, dict[str, object]] = {}
    for index, judgment in enumerate(judgments, start=1):
        audit_id = judgment.get("audit_id")
        if not isinstance(audit_id, str):
            raise ValueError(f"machine judgment {index}: audit_id must be a string")
        if audit_id in by_id:
            raise ValueError(f"duplicate machine judgment for audit ID {audit_id}")
        if audit_id not in expected_ids:
            raise ValueError(f"unknown audit ID in machine judgment: {audit_id}")
        label = judgment.get("label")
        rationale = judgment.get("rationale")
        ambiguous = judgment.get("ambiguous")
        if label not in ALLOWED_LABELS:
            raise ValueError(f"machine judgment {audit_id}: unsupported label {label!r}")
        if not isinstance(rationale, str) or not 20 <= len(rationale.strip()) <= 1_000:
            raise ValueError(
                f"machine judgment {audit_id}: rationale must contain 20 to 1,000 characters"
            )
        if not isinstance(ambiguous, bool):
            raise ValueError(f"machine judgment {audit_id}: ambiguous must be boolean")
        by_id[audit_id] = {
            "machine_label": str(label),
            "machine_rationale": rationale.strip(),
            "machine_ambiguous": ambiguous,
        }
    if set(by_id) != expected_ids:
        missing = sorted(expected_ids - set(by_id))
        raise ValueError(f"machine judgment coverage mismatch; missing {len(missing)} audit IDs")

    reconciled: list[dict[str, object]] = []
    for original in audit.mapping:
        machine = by_id[str(original["audit_id"])]
        reconciled.append(
            {
                **original,
                **machine,
                "agreement": original["original_label"] == machine["machine_label"],
                "adjudication_status": "pending"
                if original["original_label"] != machine["machine_label"]
                else "not_required",
            }
        )
    return reconciled


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def prepare_audit(dev_path: Path, frozen_path: Path, output_dir: Path) -> dict[str, object]:
    source_paths = {"development": dev_path, "frozen": frozen_path}
    source_cases = {name: load_eval_cases(path) for name, path in source_paths.items()}
    audit = build_blind_audit(source_cases)
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = output_dir / "blind-packet.jsonl"
    mapping_path = output_dir / "private-mapping.jsonl"
    _write_jsonl(packet_path, audit.packet)
    _write_jsonl(mapping_path, audit.mapping)
    protocol_path = Path("docs/evidence-audit-protocol.md")
    manifest = {
        "audit_version": AUDIT_VERSION,
        "case_count": len(audit.packet),
        "protocol_sha256": dataset_sha256(protocol_path),
        "sources": {
            name: {
                "path": str(path),
                "sha256": dataset_sha256(path),
                "case_count": len(source_cases[name]),
            }
            for name, path in source_paths.items()
        },
        "blind_packet_sha256": dataset_sha256(packet_path),
        "private_mapping_sha256": dataset_sha256(mapping_path),
        "reviewer_visible_fields": ["audit_id", "prompt"],
        "reviewer_hidden_fields": [
            "source",
            "case_id",
            "suite",
            "original_label",
            "safety_critical",
            "candidate_predictions",
            "prior_verdicts",
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the prediction-blind Nightwatch evidence audit")
    parser.add_argument("--dev", type=Path, default=Path("artifacts/v0-dev.jsonl"))
    parser.add_argument("--frozen", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence-audit-v1"),
    )
    args = parser.parse_args()
    print(json.dumps(prepare_audit(args.dev, args.frozen, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
