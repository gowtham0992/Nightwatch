from __future__ import annotations

import pytest


def test_modal_payload_boundary_rejects_empty_and_oversized_input() -> None:
    modal = pytest.importorskip("modal")
    assert modal is not None
    from nightwatch.modal_v0 import MAX_INPUT_BYTES, _bounded_payload

    with pytest.raises(ValueError, match="between 1"):
        _bounded_payload("curriculum", "")
    with pytest.raises(ValueError, match="between 1"):
        _bounded_payload("curriculum", "x" * (MAX_INPUT_BYTES + 1))
    assert _bounded_payload("curriculum", "{}\n") == b"{}\n"


def test_modal_adapter_name_blocks_volume_path_traversal() -> None:
    pytest.importorskip("modal")
    from nightwatch.modal_v0 import ARTIFACT_NAME

    assert ARTIFACT_NAME.fullmatch("v0-18a33dfd5c54-seed-20260809")
    assert ARTIFACT_NAME.fullmatch("../v0-18a33dfd5c54-seed-20260809") is None
