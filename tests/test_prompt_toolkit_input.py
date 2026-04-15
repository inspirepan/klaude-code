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



def test_set_next_prefill_stores_text() -> None:
    prompt_input: Any = _build_input("hello")
    prompt_input._next_prefill_text = None

    prompt_input.set_next_prefill("retry me")

    assert prompt_input._next_prefill_text == "retry me"
