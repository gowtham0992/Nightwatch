from __future__ import annotations

import pytest

from nightwatch.modal_scam_classifier import (
    validate_reevaluation_hashes,
    validate_scam_artifact_name,
)


@pytest.mark.parametrize(
    "artifact_name",
    [
        "scam-v0-de1e6009-2d77e636-2c73004ed3",
        "scam-v0-00000000-ffffffff-0123456789",
        "scam-candidate-v1-d0ab5041-ffca8c22-0123456789",
        "scam-candidate-v2-01234567-89abcdef-0123456789",
        "scam-candidate-v3-fedcba98-76543210-0123456789",
        "scam-candidate-v4-11111111-22222222-0123456789",
        "scam-candidate-v5-33333333-44444444-0123456789",
        "scam-candidate-v6-55555555-66666666-0123456789",
        "scam-candidate-v7-77777777-88888888-0123456789",
        "scam-candidate-v8-99999999-aaaaaaaa-0123456789",
    ],
)
def test_validate_scam_artifact_name_accepts_immutable_names(artifact_name: str) -> None:
    assert validate_scam_artifact_name(artifact_name) == artifact_name


@pytest.mark.parametrize(
    "artifact_name",
    [
        "../scam-v0-de1e6009-2d77e636-2c73004ed3",
        "scam-v0-de1e6009-2d77e636-2c73004ed3/manifest",
        "scam-v0-DE1E6009-2d77e636-2c73004ed3",
        "v0-de1e6009-2d77e636-2c73004ed3",
    ],
)
def test_validate_scam_artifact_name_rejects_untrusted_paths(artifact_name: str) -> None:
    with pytest.raises(ValueError, match="immutable scam format"):
        validate_scam_artifact_name(artifact_name)


def test_new_evidence_may_change_only_the_development_hash() -> None:
    manifest = {"mission_sha256": "mission", "development_sha256": "old"}
    expected = {"mission_sha256": "mission", "development_sha256": "new"}

    validate_reevaluation_hashes(manifest, expected, allow_new_evidence=True)

    with pytest.raises(ValueError, match="immutable adapter manifest"):
        validate_reevaluation_hashes(manifest, expected, allow_new_evidence=False)

    expected["mission_sha256"] = "other"
    with pytest.raises(ValueError, match="mission hash"):
        validate_reevaluation_hashes(manifest, expected, allow_new_evidence=True)
