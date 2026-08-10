from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from nightwatch.gcs import download_file, upload_directory
from nightwatch.train_gemma import train


def main() -> None:
    parser = argparse.ArgumentParser(description="Cloud Run entrypoint for isolated Nightwatch training")
    parser.add_argument("--curriculum-uri", required=True, help="GCS object; trainer IAM must not access eval data")
    parser.add_argument("--adapter-uri", required=True, help="Unique GCS prefix for the candidate adapter")
    parser.add_argument("--model-id", default="google/gemma-3-270m-it")
    parser.add_argument("--epochs", type=float, default=8.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="nightwatch-train-") as temporary:
        root = Path(temporary)
        curriculum_path = root / "curriculum.jsonl"
        adapter_path = root / "adapter"
        download_file(args.curriculum_uri, curriculum_path)
        train(
            args.model_id,
            curriculum_path,
            adapter_path,
            epochs=args.epochs,
            learning_rate=2e-4,
            batch_size=2,
            gradient_accumulation_steps=4,
            seed=args.seed,
        )
        upload_directory(adapter_path, args.adapter_uri)


if __name__ == "__main__":
    main()

