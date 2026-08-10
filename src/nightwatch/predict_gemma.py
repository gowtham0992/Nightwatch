from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from nightwatch.datasets import ALLOWED_LABELS, load_eval_cases

LABEL_PATTERN = re.compile(r"\b(page_now|investigate|defer)\b", re.IGNORECASE)


def parse_label(text: str) -> str:
    matches = LABEL_PATTERN.findall(text)
    unique = {match.casefold() for match in matches}
    return next(iter(unique)) if len(unique) == 1 else "invalid"


def predict(model_id: str, adapter_path: Path | None, eval_path: Path, output_path: Path) -> None:
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit("Inference dependencies are missing. Run: uv sync --extra train") from exc

    cases = load_eval_cases(eval_path)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    base_model = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(base_model, str(adapter_path)) if adapter_path else base_model
    model.eval()

    rows: list[dict[str, str]] = []
    for case in cases:
        messages = [
            {
                "role": "system",
                "content": (
                    "Classify the production alert. Reply with exactly one label: "
                    "page_now, investigate, or defer."
                ),
            },
            {"role": "user", "content": case.prompt},
        ]
        encoded = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        ).to(model.device)
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=12,
                pad_token_id=tokenizer.eos_token_id,
            )
        new_tokens = generated[0, encoded["input_ids"].shape[-1] :]
        label = parse_label(tokenizer.decode(new_tokens, skip_special_tokens=True))
        rows.append({"id": case.case_id, "label": label})

    if not all(row["label"] in ALLOWED_LABELS for row in rows):
        print("One or more outputs were invalid; the deterministic gate will reject this candidate.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate frozen-eval predictions with Gemma")
    parser.add_argument("--model-id", default="google/gemma-3-270m-it")
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--eval", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    predict(args.model_id, args.adapter, args.eval, args.output)


if __name__ == "__main__":
    main()

