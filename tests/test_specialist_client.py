from __future__ import annotations

import pytest

from nightwatch.specialist_client import _origin


@pytest.mark.parametrize(
    "url",
    [
        "http://specialist.example.run.app",
        "https://user@specialist.example.run.app",
        "https://specialist.example.run.app?redirect=evil",
        "https://specialist.example.run.app#fragment",
    ],
)
def test_origin_rejects_unsafe_endpoint_forms(url: str) -> None:
    with pytest.raises(ValueError):
        _origin(url)


def test_origin_discards_path_but_preserves_authority() -> None:
    assert _origin("https://specialist.example.run.app/a2a") == "https://specialist.example.run.app"
