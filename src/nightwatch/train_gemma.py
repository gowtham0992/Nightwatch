from __future__ import annotations

import argparse
import json
from pathlib import Path

from nightwatch.datasets import dataset_sha256, load_curriculum
from nightwatch.model_config import GEMMA_MODEL_ID, GEMMA_MODEL_REVISION


def train(
    model_id: str,
    curriculum_path: Path,
    output_dir: Path,
    *,
    epochs: float,
    learning_rate: float,
    batch_size: int,
    gradient_accumulation_steps: int,
    seed: int,
    model_revision: str | None = None,
) -> dict[str, object]:
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise SystemExit("Training dependencies are missing. Run: uv sync --extra train") from exc

    examples = load_curriculum(curriculum_path)
    rows = [
        {
            "prompt": [
                {
                    "role": "system",
                    "content": (
                        "Classify the production alert. Reply with exactly one label: "
                        "page_now, investigate, or defer."
                    ),
                },
                {"role": "user", "content": row["prompt"]},
            ],
            "completion": [{"role": "assistant", "content": row["label"]}],
        }
        for row in examples
    ]
    dataset = Dataset.from_list(rows)
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=model_revision)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        revision=model_revision,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
    )
    model.config.use_cache = False

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "v_proj"],
    )
    args = SFTConfig(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        learning_rate=learning_rate,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        completion_only_loss=True,
        max_length=512,
        logging_steps=1,
        save_strategy="no",
        report_to="none",
        seed=seed,
    )
    trainer = SFTTrainer(
        model=model,
        args=args,
        train_dataset=dataset,
        processing_class=tokenizer,
        peft_config=peft_config,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    manifest = {
        "model_id": model_id,
        "model_revision": model_revision,
        "curriculum_sha256": dataset_sha256(curriculum_path),
        "examples": len(examples),
        "epochs": epochs,
        "learning_rate": learning_rate,
        "batch_size": batch_size,
        "gradient_accumulation_steps": gradient_accumulation_steps,
        "seed": seed,
    }
    (output_dir / "nightwatch-training.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a Gemma 3 270M Nightwatch LoRA adapter")
    parser.add_argument("--model-id", default=GEMMA_MODEL_ID)
    parser.add_argument("--model-revision", default=GEMMA_MODEL_REVISION)
    parser.add_argument("--curriculum", type=Path, default=Path("data/curriculum/silent_failure.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/adapter"))
    parser.add_argument("--epochs", type=float, default=8.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    train(
        args.model_id,
        args.curriculum,
        args.output_dir,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        seed=args.seed,
        model_revision=args.model_revision,
    )


if __name__ == "__main__":
    main()
