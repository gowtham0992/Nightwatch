from __future__ import annotations

import argparse
import json

from nightwatch.firestore_journal import FirestoreJournal
from nightwatch.mission_orchestrator import SAFETY_270M_V1, advance_mission
from nightwatch.modal_training_stage import (
    GCSModalCallStore,
    ModalClassifierTrainingStage,
)
from nightwatch.safety_mission_stages import SafetyQualificationStageExecutor
from nightwatch.stage_artifacts import GCSStageArtifactStore

DEFAULT_PROJECT = "nightwatch-agentic-0992"
DEFAULT_ARTIFACT_BUCKET = "nightwatch-agentic-0992-mission-artifacts"


def run(cycle_id: str, *, project: str, artifact_bucket: str, steps: int) -> list[dict[str, object]]:
    if not 1 <= steps <= 6:
        raise ValueError("steps must be between 1 and 6")
    journal = FirestoreJournal.from_default(project=project)
    artifacts = GCSStageArtifactStore.from_default(
        project=project,
        bucket_name=artifact_bucket,
    )
    training = ModalClassifierTrainingStage(
        artifacts,
        GCSModalCallStore.from_default(project=project, bucket_name=artifact_bucket),
    )
    executor = SafetyQualificationStageExecutor(artifacts, training_stage=training)
    advances: list[dict[str, object]] = []
    for _ in range(steps):
        result = advance_mission(
            cycle_id,
            SAFETY_270M_V1.manifest_id,
            journal=journal,
            executor=executor,
        )
        advances.append(
            {
                "cycle_id": result.cycle_id,
                "manifest_id": result.manifest_id,
                "stage": result.stage.value,
                "terminal": result.terminal,
                "entry_hash": result.entry_hash,
            }
        )
        if result.terminal:
            break
    return advances


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Advance the one approved Nightwatch mission through real bounded stages"
    )
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--artifact-bucket", default=DEFAULT_ARTIFACT_BUCKET)
    parser.add_argument("--steps", type=int, default=1)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.cycle_id,
                project=args.project,
                artifact_bucket=args.artifact_bucket,
                steps=args.steps,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
