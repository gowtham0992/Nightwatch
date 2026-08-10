import pytest

from nightwatch.predict_gemma import build_messages, parse_label


def test_parse_label_accepts_one_unambiguous_label() -> None:
    assert parse_label("PAGE_NOW\n") == "page_now"


def test_parse_label_rejects_multiple_labels() -> None:
    assert parse_label("investigate or defer") == "invalid"


def test_parse_label_rejects_explanation_without_label() -> None:
    assert parse_label("This needs attention.") == "invalid"


def test_prompt_only_baseline_formats_few_shot_turns_before_eval_prompt() -> None:
    messages = build_messages(
        "Current production alert",
        [
            {"prompt": "Example alert one", "label": "page_now"},
            {"prompt": "Example alert two", "label": "defer"},
        ],
    )

    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert messages[-1] == {"role": "user", "content": "Current production alert"}
    assert messages[2] == {"role": "assistant", "content": "page_now"}


def test_prompt_only_baseline_caps_examples_to_predeclared_context_budget() -> None:
    examples = [{"prompt": f"Example alert {index}", "label": "defer"} for index in range(17)]

    with pytest.raises(ValueError, match="at most 16"):
        build_messages("Current production alert", examples)
