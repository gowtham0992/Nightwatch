from pathlib import Path


SCAM_EVIDENCE = {
    "artifacts/scam-safety/repair-authoring-v5.json",
    "artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-development-predictions.jsonl",
    "artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-development-report.json",
    "artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-evidence-ffca8c22-predictions.jsonl",
    "artifacts/scam-safety/scam-v0-de1e6009-2d77e636-c0e947096d-repair-plan.json",
}


def test_cloud_and_docker_contexts_admit_every_private_scam_evidence_file() -> None:
    dockerfile = Path("containers/mission.Dockerfile").read_text(encoding="utf-8")
    dockerignore = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    gcloudignore = Path(".gcloudignore").read_text(encoding="utf-8").splitlines()

    for source in SCAM_EVIDENCE:
        assert f"COPY {source} " in dockerfile
        assert f"!{source}" in dockerignore
        assert f"!{source}" in gcloudignore
        assert Path(source).is_file()
