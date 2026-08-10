from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from nightwatch.datasets import ALLOWED_LABELS, load_curriculum, load_eval_cases

LABEL_PATTERN = re.compile(r"\b(page_now|investigate|defer)\b", re.IGNORECASE)
MAX_FEW_SHOT_EXAMPLES = 16


def parse_label(text: str) -> str:
    matches = LABEL_PATTERN.findall(text)
    unique = {match.casefold() for match in matches}
    return next(iter(unique)) if len(unique) == 1 else "invalid"


def build_messages(prompt: str, few_shot_examples: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(few_shot_examples) > MAX_FEW_SHOT_EXAMPLES:
        raise ValueError(f"prompt-only baseline accepts at most {MAX_FEW_SHOT_EXAMPLES} examples")

    messages = [
        {
            "role": "system",
            "content": (
                "Classify the production alert. Reply with exactly one label: "
                "page_now, investigate, or defer."
            ),
        }
    ]
    for example in few_shot_examples:
        messages.extend(
            [
                {"role": "user", "content": example["prompt"]},
                {"role": "assistant", "content": example["label"]},
            ]
        )
    messages.append({"role": "user", "content": prompt})
    return messages


def predict(
    model_id: str,
    adapter_path: Path | None,
    eval_path: Path,
    output_path: Path,
    few_shot_path: Path | None = None,
) -> None:
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit("Inference dependencies are missing. Run: uv sync --extra train") from exc

    cases = load_eval_cases(eval_path)
    few_shot_examples = load_curriculum(few_shot_path) if few_shot_path else []
    if len(few_shot_examples) > MAX_FEW_SHOT_EXAMPLES:
        raise SystemExit(
            f"Prompt-only baseline accepts at most {MAX_FEW_SHOT_EXAMPLES} examples; "
            f"received {len(few_shot_examples)}"
        )
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
        messages = build_messages(case.prompt, few_shot_examples)
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
    parser.add_argument(
        "--few-shot",
        type=Path,
        help="Optional curriculum JSONL for the predeclared prompt-only comparison (maximum 16 examples)",
    )
    parser.add_argument("--eval", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.adapter and args.few_shot:
        raise SystemExit("--adapter and --few-shot are separate experiment arms and cannot be combined")
    predict(args.model_id, args.adapter, args.eval, args.output, args.few_shot)


if __name__ == "__main__":
    main()
