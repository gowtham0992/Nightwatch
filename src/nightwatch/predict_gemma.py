from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from nightwatch.datasets import ALLOWED_LABELS, load_curriculum, load_eval_cases

LABEL_PATTERN = re.compile(r"\b(page_now|investigate|defer)\b", re.IGNORECASE)
MAX_PROMPT_EXAMPLES = 128
LABEL_ORDER = ("page_now", "investigate", "defer")


def parse_label(text: str) -> str:
    matches = LABEL_PATTERN.findall(text)
    unique = {match.casefold() for match in matches}
    return next(iter(unique)) if len(unique) == 1 else "invalid"


def build_messages(prompt: str, few_shot_examples: list[dict[str, str]]) -> list[dict[str, str]]:
    if len(few_shot_examples) > MAX_PROMPT_EXAMPLES:
        raise ValueError(f"prompt-only baseline accepts at most {MAX_PROMPT_EXAMPLES} examples")

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


def select_few_shot_examples(
    examples: list[dict[str, str]],
    *,
    count: int | None,
) -> list[dict[str, str]]:
    selected_count = len(examples) if count is None else count
    if selected_count < 1:
        raise ValueError("prompt-only baseline requires at least one example")
    if selected_count > len(examples):
        raise ValueError(
            f"prompt-only baseline requested {selected_count} examples but only {len(examples)} exist"
        )
    if selected_count > MAX_PROMPT_EXAMPLES:
        raise ValueError(f"prompt-only baseline accepts at most {MAX_PROMPT_EXAMPLES} examples")
    if count is None:
        return list(examples)

    indexed_by_label = {
        label: [(index, example) for index, example in enumerate(examples) if example["label"] == label]
        for label in LABEL_ORDER
    }
    base, remainder = divmod(selected_count, len(LABEL_ORDER))
    quotas = {
        label: min(len(indexed_by_label[label]), base + (index < remainder))
        for index, label in enumerate(LABEL_ORDER)
    }
    selected = [
        item
        for label in LABEL_ORDER
        for item in indexed_by_label[label][: quotas[label]]
    ]
    selected_indexes = {index for index, _ in selected}
    if len(selected) < selected_count:
        remaining = [
            (index, example)
            for index, example in enumerate(examples)
            if index not in selected_indexes
        ]
        selected.extend(remaining[: selected_count - len(selected)])
    ordered = sorted(selected, key=lambda item: item[0])
    return [example for _, example in ordered]


def predict(
    model_id: str,
    adapter_path: Path | None,
    eval_path: Path,
    output_path: Path,
    few_shot_path: Path | None = None,
    few_shot_count: int | None = None,
) -> None:
    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit("Inference dependencies are missing. Run: uv sync --extra train") from exc

    cases = load_eval_cases(eval_path)
    loaded_examples = load_curriculum(few_shot_path) if few_shot_path else []
    try:
        few_shot_examples = (
            select_few_shot_examples(loaded_examples, count=few_shot_count)
            if few_shot_path
            else []
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
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
        help="Optional curriculum JSONL for a prompt-only comparison (maximum 128 examples)",
    )
    parser.add_argument(
        "--few-shot-count",
        type=int,
        help="Use a label-stratified first-N subset; omit to run the matched-count prompt arm",
    )
    parser.add_argument("--eval", type=Path, default=Path("data/eval/frozen.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.adapter and args.few_shot:
        raise SystemExit("--adapter and --few-shot are separate experiment arms and cannot be combined")
    if args.few_shot_count is not None and args.few_shot is None:
        raise SystemExit("--few-shot-count requires --few-shot")
    predict(
        args.model_id,
        args.adapter,
        args.eval,
        args.output,
        args.few_shot,
        args.few_shot_count,
    )


if __name__ == "__main__":
    main()
