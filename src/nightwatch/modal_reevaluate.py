from __future__ import annotations

import json
from pathlib import Path

from nightwatch.modal_v0 import app, evaluate_saved_v0


@app.local_entrypoint()
def reevaluate(
    artifact_name: str,
    eval_path: str = "data/eval/frozen.jsonl",
    output_dir: str = "artifacts",
    classification_mode: str = "label_logprob",
) -> None:
    result = evaluate_saved_v0.remote(
        artifact_name,
        Path(eval_path).read_text(encoding="utf-8"),
        classification_mode=classification_mode,
    )
    predictions = str(result.pop("predictions_jsonl"))
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stem = f"{artifact_name}-{classification_mode}"
    (destination / f"{stem}-predictions.jsonl").write_text(predictions, encoding="utf-8")
    report_path = destination / f"{stem}-report.json"
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), **result["v0_assessment"]}, indent=2))
