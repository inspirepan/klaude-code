from types import SimpleNamespace
from typing import Any

from klaude_code.tui.components.user_input import USER_MESSAGE_MARK
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput


def _build_input(text: str) -> PromptToolkitInput:
    prompt_input: Any = object.__new__(PromptToolkitInput)
    prompt_input._prompt_text = USER_MESSAGE_MARK
    prompt_input._session = SimpleNamespace(default_buffer=SimpleNamespace(text=text))
    prompt_input._clipboard_has_image = False
    prompt_input._prompt_suggestion = None
    return prompt_input  # type: ignore[return-value]


def test_set_next_prefill_stores_text() -> None:
    prompt_input: Any = _build_input("hello")
    prompt_input._next_prefill_text = None

    prompt_input.set_next_prefill("retry me")

    assert prompt_input._next_prefill_text == "retry me"


def test_placeholder_shows_paste_image_hint_with_prompt_suggestion() -> None:
    prompt_input = _build_input("")
    prompt_input._prompt_suggestion = "run tests"
    prompt_input._clipboard_has_image = True

    placeholder = prompt_input._build_placeholder()

    assert ("class:prompt-suggestion", "run tests") in placeholder
    assert any("ctrl+v to paste image" in text and "\n" not in text for _style, text in placeholder)
