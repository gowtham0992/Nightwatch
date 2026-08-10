from argparse import Namespace
import json
from pathlib import Path

from nightwatch.cli import run_gate_fixture


def test_gate_fixture_writes_report_but_never_fabricates_lifecycle_journal(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    args = Namespace(
        eval=Path("data/eval/fixture.jsonl"),
        curriculum=Path("data/curriculum/silent_failure.jsonl"),
        baseline=Path("data/predictions/baseline.jsonl"),
        candidate=Path("data/predictions/good_candidate.jsonl"),
        report=report,
        journal=tmp_path / "fabricated-journal.jsonl",
        cycle_id="fixture-must-not-be-journaled",
    )

    assert run_gate_fixture(args) == 0
    assert report.exists()
    assert not args.journal.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["evidence"]["eval_sha256"]
    assert payload["evidence"]["curriculum_sha256"]
    assert payload["evidence"]["near_duplicate_threshold"] == 0.75
    assert isinstance(payload["evidence"]["near_duplicate_advisories"], list)
