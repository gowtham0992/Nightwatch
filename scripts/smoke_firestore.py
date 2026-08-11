from __future__ import annotations

import argparse
import os
import uuid

from nightwatch.contracts import Stage
from nightwatch.firestore_journal import FirestoreJournal


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise the real Firestore journal transaction")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    access_token = os.environ.get("NIGHTWATCH_GCLOUD_ACCESS_TOKEN")
    if not access_token:
        raise SystemExit("NIGHTWATCH_GCLOUD_ACCESS_TOKEN is required")

    from google.cloud import firestore
    from google.oauth2.credentials import Credentials

    credentials = Credentials(token=access_token)
    client = firestore.Client(project=args.project, credentials=credentials)
    collection = "nightwatch_contract_tests"
    cycle_id = f"firestore-smoke-{uuid.uuid4().hex[:12]}"
    journal = FirestoreJournal(
        client,
        transactional=firestore.transactional,
        collection=collection,
    )
    mission_ref = client.collection(collection).document(cycle_id)
    entry_ref = mission_ref.collection("entries").document(Stage.CREATED.value)

    try:
        first = journal.append_stage(
            cycle_id,
            Stage.CREATED,
            {
                "kind": "firestore_contract_smoke_test",
                "project": args.project,
                "source_commit": "32fd9d2",
            },
        )
        replay = journal.append_stage(
            cycle_id,
            Stage.CREATED,
            {
                "kind": "firestore_contract_smoke_test",
                "project": args.project,
                "source_commit": "32fd9d2",
            },
        )
        entries = journal.read_cycle(cycle_id)
        if replay != first or entries != [first]:
            raise RuntimeError("Firestore replay was not single-effect")
        print(
            f"verified {cycle_id}: one {first.stage.value} entry, "
            f"head {first.entry_hash}, replay single-effect"
        )
    finally:
        entry_ref.delete()
        mission_ref.delete()
        if entry_ref.get().exists or mission_ref.get().exists:
            raise RuntimeError(f"temporary contract-test mission {cycle_id} was not fully removed")
        print(f"removed and verified temporary contract-test mission {cycle_id}")


if __name__ == "__main__":
    main()
