from types import SimpleNamespace
from typing import Any

from prompt_toolkit.formatted_text import to_formatted_text

from klaude_code.tui.components.user_input import USER_MESSAGE_MARK
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput


def _build_input(text: str) -> PromptToolkitInput:
    prompt_input: Any = object.__new__(PromptToolkitInput)
    prompt_input._prompt_text = USER_MESSAGE_MARK
    prompt_input._session = SimpleNamespace(default_buffer=SimpleNamespace(text=text))
    return prompt_input  # type: ignore[return-value]


def test_prompt_stays_default_in_bash_mode() -> None:
    prompt_input: Any = _build_input("!echo hi")

    prompt = to_formatted_text(prompt_input._get_prompt_message())
    rprompt = to_formatted_text(prompt_input._get_rprompt_message())

    assert prompt == [("ansicyan bold", USER_MESSAGE_MARK)]
    assert rprompt == [("ansigreen", "(bash mode)")]


def test_rprompt_hidden_outside_bash_mode() -> None:
    prompt_input: Any = _build_input("hello")

    prompt = to_formatted_text(prompt_input._get_prompt_message())
    rprompt = to_formatted_text(prompt_input._get_rprompt_message())

    assert prompt == [("ansicyan bold", USER_MESSAGE_MARK)]
    assert rprompt == []
