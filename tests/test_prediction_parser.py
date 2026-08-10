import pytest

from nightwatch.predict_gemma import build_messages, parse_label, select_few_shot_examples


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
    examples = [{"prompt": f"Example alert {index}", "label": "defer"} for index in range(129)]

    with pytest.raises(ValueError, match="at most 128"):
        build_messages("Current production alert", examples)


def test_practical_prompt_arm_selects_first_label_stratified_examples() -> None:
    examples = [
        {"prompt": "page first", "label": "page_now"},
        {"prompt": "page second", "label": "page_now"},
        {"prompt": "defer first", "label": "defer"},
        {"prompt": "investigate first", "label": "investigate"},
        {"prompt": "page third", "label": "page_now"},
        {"prompt": "defer second", "label": "defer"},
        {"prompt": "investigate second", "label": "investigate"},
    ]

    selected = select_few_shot_examples(examples, count=6)

    assert [example["prompt"] for example in selected] == [
        "page first",
        "page second",
        "defer first",
        "investigate first",
        "defer second",
        "investigate second",
    ]


def test_matched_prompt_arm_preserves_all_examples_in_generation_order() -> None:
    examples = [
        {"prompt": "first", "label": "page_now"},
        {"prompt": "second", "label": "defer"},
    ]

    assert select_few_shot_examples(examples, count=None) == examples
