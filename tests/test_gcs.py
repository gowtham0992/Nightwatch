import pytest

from nightwatch.gcs import GcsUriError, parse_gs_uri


def test_parse_gs_uri_returns_bucket_and_object() -> None:
    assert parse_gs_uri("gs://nightwatch-curricula/cycles/001/train.jsonl") == (
        "nightwatch-curricula",
        "cycles/001/train.jsonl",
    )


@pytest.mark.parametrize(
    "uri",
    ["https://example.com/file", "gs://", "gs://bucket", "gs://bucket/object?generation=1"],
)
def test_parse_gs_uri_rejects_non_object_or_ambiguous_uri(uri: str) -> None:
    with pytest.raises(GcsUriError):
        parse_gs_uri(uri)

