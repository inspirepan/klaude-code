from __future__ import annotations

from typing import Any, cast

import pytest
from prompt_toolkit.document import Document

from klaude_code.protocol.commands import CommandInfo
from klaude_code.tui.input.completers import (
    _ComboCompleter,  # pyright: ignore[reportPrivateUsage]
    _SkillCompleter,  # pyright: ignore[reportPrivateUsage]
    _SlashCommandCompleter,  # pyright: ignore[reportPrivateUsage]
)


def _command_info_provider() -> list[CommandInfo]:
    return [
        CommandInfo(name="copy", summary="copy command"),
        CommandInfo(name="model", summary="model command"),
    ]


@pytest.fixture(autouse=True)
def _mock_skills(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    skills: list[tuple[str, str, str]] = [
        ("copy", "copy skill", "project"),
        ("publish", "publish skill", "user"),
    ]
    monkeypatch.setattr(_SkillCompleter, "_get_available_skills", lambda _self: skills)  # pyright: ignore[reportUnknownArgumentType,reportUnknownLambdaType]
    monkeypatch.setattr(_SlashCommandCompleter, "_get_available_skills", lambda _self: skills)  # pyright: ignore[reportUnknownArgumentType,reportUnknownLambdaType]


def test_slash_mixed_completion_prioritizes_command_and_hides_same_name_skill() -> None:
    completer = _ComboCompleter(command_info_provider=_command_info_provider)
    completions = list(completer.get_completions(Document(text="/", cursor_position=1), cast(Any, None)))
    texts = [completion.text for completion in completions]

    assert texts[0] == "/copy "
    assert "/copy " in texts
    assert "/model " in texts
    assert "/skill:copy " in texts
    assert "/skill:publish " in texts
    assert texts.count("/copy ") == 1


def test_double_slash_completion_shows_only_skills() -> None:
    completer = _ComboCompleter(command_info_provider=_command_info_provider)
    completions = list(completer.get_completions(Document(text="//", cursor_position=2), cast(Any, None)))
    texts = [completion.text for completion in completions]

    assert "//skill:copy " in texts
    assert "//skill:publish " in texts
    assert "/copy " not in texts
    assert "/model " not in texts


def test_inline_slash_skill_completion_works() -> None:
    completer = _ComboCompleter(command_info_provider=_command_info_provider)
    doc = Document(text="please /pub", cursor_position=len("please /pub"))
    completions = list(completer.get_completions(doc, cast(Any, None)))
    texts = [completion.text for completion in completions]

    assert "/skill:publish " in texts


def test_skill_display_uses_colored_marker_and_plain_description() -> None:
    completer = _ComboCompleter(command_info_provider=_command_info_provider)
    completions = list(completer.get_completions(Document(text="//", cursor_position=2), cast(Any, None)))
    publish = next(completion for completion in completions if completion.text == "//skill:publish ")

    assert publish.display_text == "• skill:publish"
    assert publish.display_meta_text == "publish skill"


def test_command_display_uses_gray_marker() -> None:
    completer = _ComboCompleter(command_info_provider=_command_info_provider)
    completions = list(completer.get_completions(Document(text="/mo", cursor_position=3), cast(Any, None)))
    model = next(completion for completion in completions if completion.text == "/model ")

    assert model.display_text == "• model"


def test_legacy_dollar_skill_completion_removed() -> None:
    completer = _ComboCompleter(command_info_provider=_command_info_provider)
    doc = Document(text="please $pub", cursor_position=len("please $pub"))
    completions = list(completer.get_completions(doc, cast(Any, None)))

    assert completions == []
