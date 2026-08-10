from nightwatch.predict_gemma import parse_label


def test_parse_label_accepts_one_unambiguous_label() -> None:
    assert parse_label("PAGE_NOW\n") == "page_now"


def test_parse_label_rejects_multiple_labels() -> None:
    assert parse_label("investigate or defer") == "invalid"


def test_parse_label_rejects_explanation_without_label() -> None:
    assert parse_label("This needs attention.") == "invalid"

