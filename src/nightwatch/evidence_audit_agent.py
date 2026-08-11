from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, cast

from nightwatch.datasets import ALLOWED_LABELS
from nightwatch.evidence_audit import BlindAudit, reconcile_machine_judgments

MODEL_ID = "gemini-3.6-flash"
TEMPERATURE = 0.0
DEFAULT_BATCH_SIZE = 20
MAX_CONCURRENCY = 3


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_batch_judgments(
    packet: Iterable[dict[str, str]],
    judgments: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    expected_ids = [row["audit_id"] for row in packet]
    expected_set = set(expected_ids)
    by_id: dict[str, dict[str, object]] = {}
    for index, row in enumerate(judgments, start=1):
        audit_id = row.get("audit_id")
        if not isinstance(audit_id, str):
            raise ValueError(f"batch judgment {index}: audit_id must be a string")
        if audit_id in by_id:
            raise ValueError(f"duplicate batch judgment for audit ID {audit_id}")
        if audit_id not in expected_set:
            raise ValueError(f"unknown audit ID in batch judgment: {audit_id}")
        label = row.get("label")
        rationale = row.get("rationale")
        ambiguous = row.get("ambiguous")
        if label not in ALLOWED_LABELS:
            raise ValueError(f"batch judgment {audit_id}: unsupported label {label!r}")
        if not isinstance(rationale, str) or not 20 <= len(rationale.strip()) <= 1_000:
            raise ValueError(
                f"batch judgment {audit_id}: rationale must contain 20 to 1,000 characters"
            )
        if not isinstance(ambiguous, bool):
            raise ValueError(f"batch judgment {audit_id}: ambiguous must be boolean")
        by_id[audit_id] = {
            "audit_id": audit_id,
            "label": str(label),
            "rationale": rationale.strip(),
            "ambiguous": ambiguous,
        }
    if set(by_id) != expected_set:
        raise ValueError(
            f"batch judgment coverage mismatch: expected {len(expected_set)}, received {len(by_id)}"
        )
    return [by_id[audit_id] for audit_id in expected_ids]


def build_adjudication_packet(
    packet: Iterable[dict[str, str]],
    reconciled: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    prompts: dict[str, str] = {}
    for index, row in enumerate(packet, start=1):
        if set(row) != {"audit_id", "prompt"}:
            raise ValueError(f"blind packet row {index}: unexpected reviewer-visible field")
        audit_id = row.get("audit_id")
        prompt = row.get("prompt")
        if not isinstance(audit_id, str) or not isinstance(prompt, str):
            raise ValueError(f"blind packet row {index}: audit_id and prompt must be strings")
        if audit_id in prompts:
            raise ValueError(f"duplicate blind packet audit ID: {audit_id}")
        prompts[audit_id] = prompt

    decisions: list[dict[str, object]] = []
    for index, row in enumerate(reconciled, start=1):
        if row.get("agreement") is True:
            continue
        if row.get("agreement") is not False:
            raise ValueError(f"reconciliation row {index}: agreement must be boolean")
        audit_id = row.get("audit_id")
        if not isinstance(audit_id, str) or audit_id not in prompts:
            raise ValueError(f"reconciliation row {index}: unknown audit ID {audit_id!r}")
        decisions.append(
            {
                "audit_id": audit_id,
                "source": row.get("source"),
                "case_id": row.get("case_id"),
                "original_suite": row.get("original_suite"),
                "safety_critical": row.get("safety_critical"),
                "prompt": prompts[audit_id],
                "retained_label": row.get("original_label"),
                "machine_label": row.get("machine_label"),
                "machine_rationale": row.get("machine_rationale"),
                "machine_ambiguous": row.get("machine_ambiguous"),
                "adjudicated_label": None,
                "adjudicator_rationale": None,
                "adjudicator": None,
                "adjudication_status": "pending",
            }
        )
    return sorted(
        decisions,
        key=lambda row: (
            str(row["source"]),
            str(row["original_suite"]),
            str(row["case_id"]),
        ),
    )


async def _judge_batch(
    packet: list[dict[str, str]],
    rubric: str,
    batch_index: int,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, object]]:
    try:
        from google.adk.agents import LlmAgent
        from google.adk.runners import InMemoryRunner
        from google.genai import types
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise SystemExit("Agent dependencies are missing. Run: uv sync --extra agent") from exc

    required_count = len(packet)

    class MachineJudgment(BaseModel):
        audit_id: str
        label: str
        rationale: str = Field(min_length=20, max_length=1_000)
        ambiguous: bool

    class MachineBatch(BaseModel):
        judgments: list[MachineJudgment] = Field(
            min_length=required_count,
            max_length=required_count,
        )

    agent = LlmAgent(
        name=f"evidence_audit_batch_{batch_index:03d}",
        model=MODEL_ID,
        description="Applies a fixed incident-triage labeling rubric to prediction-blind evidence.",
        instruction=(
            "Apply the supplied labeling rubric literally to every supplied case. Return exactly one "
            "judgment for every audit_id and repeat each audit_id exactly. Choose only page_now, "
            "investigate, or defer. Base the label solely on the prompt and rubric. Do not infer a hidden "
            "suite, prior label, model prediction, desired outcome, or candidate identity. Mark ambiguous "
            "true when two labels remain reasonably defensible under the rubric, while still choosing the "
            "single best label. The rationale must cite decisive prompt evidence and rubric language; it "
            "must not mention datasets, audits, models, answer keys, or previous decisions."
        ),
        output_schema=MachineBatch,
        output_key=f"evidence_audit_batch_{batch_index:03d}",
        generate_content_config=types.GenerateContentConfig(
            temperature=TEMPERATURE,
            max_output_tokens=8_192,
        ),
    )
    last_error: Exception | None = None
    async with semaphore:
        for attempt in range(1, 4):
            try:
                events = await InMemoryRunner(agent=agent).run_debug(
                    json.dumps(
                        {
                            "rubric": rubric,
                            "cases": packet,
                            "required_count": required_count,
                            "attempt": attempt,
                        },
                        sort_keys=True,
                    ),
                    quiet=True,
                )
                final_text = ""
                for event in events:
                    if event.is_final_response() and event.content:
                        final_text = "".join(
                            part.text or ""
                            for part in event.content.parts
                            if not getattr(part, "thought", False)
                        )
                batch = MachineBatch.model_validate_json(final_text)
                return validate_batch_judgments(
                    packet,
                    [item.model_dump() for item in batch.judgments],
                )
            except Exception as exc:
                last_error = exc
    raise RuntimeError(
        f"Gemini audit batch {batch_index} failed after three attempts: "
        f"{type(last_error).__name__}"
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


async def run_machine_audit(
    packet_path: Path,
    mapping_path: Path,
    rubric_path: Path,
    output_dir: Path,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, object]:
    if not 5 <= batch_size <= 30:
        raise ValueError("batch_size must be between 5 and 30")
    raw_packet = _read_jsonl(packet_path)
    packet: list[dict[str, str]] = []
    for index, row in enumerate(raw_packet, start=1):
        if set(row) != {"audit_id", "prompt"}:
            raise ValueError(f"blind packet row {index}: unexpected reviewer-visible field")
        audit_id = row["audit_id"]
        prompt = row["prompt"]
        if not isinstance(audit_id, str) or not isinstance(prompt, str):
            raise ValueError(f"blind packet row {index}: audit_id and prompt must be strings")
        packet.append({"audit_id": audit_id, "prompt": prompt})
    mapping = _read_jsonl(mapping_path)
    audit = BlindAudit(tuple(packet), tuple(mapping))
    rubric = rubric_path.read_text(encoding="utf-8")
    if not rubric.strip() or len(rubric) > 20_000:
        raise ValueError("labeling rubric must contain 1 to 20,000 characters")

    batches = [packet[start : start + batch_size] for start in range(0, len(packet), batch_size)]
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    batch_results = await asyncio.gather(
        *[
            _judge_batch(batch, rubric, index, semaphore)
            for index, batch in enumerate(batches, start=1)
        ]
    )
    judgments = [row for batch in batch_results for row in batch]
    reconciled = reconcile_machine_judgments(audit, judgments)
    output_dir.mkdir(parents=True, exist_ok=True)
    judgment_path = output_dir / "machine-judgments.jsonl"
    reconciliation_path = output_dir / "reconciliation.jsonl"
    adjudication_path = output_dir / "adjudication-packet.jsonl"
    _write_jsonl(judgment_path, judgments)
    _write_jsonl(reconciliation_path, reconciled)
    _write_jsonl(adjudication_path, build_adjudication_packet(packet, reconciled))

    disagreements = [row for row in reconciled if not row["agreement"]]
    ambiguity_count = sum(bool(row["machine_ambiguous"]) for row in reconciled)
    disagreement_segments = Counter(
        (str(row["source"]), str(row["original_suite"])) for row in disagreements
    )
    transitions = Counter(
        (str(row["original_label"]), str(row["machine_label"])) for row in disagreements
    )
    summary = {
        "reviewer": {
            "model": MODEL_ID,
            "temperature": TEMPERATURE,
            "batch_size": batch_size,
            "batch_count": len(batches),
            "maximum_concurrency": MAX_CONCURRENCY,
        },
        "inputs": {
            "blind_packet_sha256": _sha256(packet_path),
            "private_mapping_sha256": _sha256(mapping_path),
            "rubric_sha256": _sha256(rubric_path),
        },
        "case_count": len(reconciled),
        "agreement_count": len(reconciled) - len(disagreements),
        "disagreement_count": len(disagreements),
        "machine_ambiguous_count": ambiguity_count,
        "disagreements_by_source_and_suite": {
            f"{source}/{suite}": count
            for (source, suite), count in sorted(disagreement_segments.items())
        },
        "label_transitions": {
            f"{original}->{machine}": count
            for (original, machine), count in sorted(transitions.items())
        },
        "machine_judgments_sha256": _sha256(judgment_path),
        "reconciliation_sha256": _sha256(reconciliation_path),
        "adjudication_packet_sha256": _sha256(adjudication_path),
        "adjudication_complete": False,
        "evidence_v2_exists": False,
    }
    summary_path = output_dir / "machine-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the prediction-blind Gemini evidence audit")
    parser.add_argument(
        "--packet",
        type=Path,
        default=Path("artifacts/evidence-audit-v1/blind-packet.jsonl"),
    )
    parser.add_argument(
        "--mapping",
        type=Path,
        default=Path("artifacts/evidence-audit-v1/private-mapping.jsonl"),
    )
    parser.add_argument("--rubric", type=Path, default=Path("data/eval/LABELING.md"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence-audit-v1"),
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--adjudication-only",
        action="store_true",
        help="Build the pending adjudication packet from existing reconciliation output",
    )
    args = parser.parse_args()
    if args.adjudication_only:
        raw_packet = _read_jsonl(args.packet)
        packet = cast(list[dict[str, str]], raw_packet)
        reconciled = _read_jsonl(args.output_dir / "reconciliation.jsonl")
        adjudication_path = args.output_dir / "adjudication-packet.jsonl"
        _write_jsonl(adjudication_path, build_adjudication_packet(packet, reconciled))
        print(
            json.dumps(
                {
                    "adjudication_packet": str(adjudication_path),
                    "sha256": _sha256(adjudication_path),
                    "pending_count": sum(row.get("agreement") is False for row in reconciled),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    summary = asyncio.run(
        run_machine_audit(
            args.packet,
            args.mapping,
            args.rubric,
            args.output_dir,
            batch_size=args.batch_size,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
