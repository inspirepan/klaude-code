from __future__ import annotations

import sys

from _pytest.monkeypatch import MonkeyPatch

from klaude_code.tui.terminal.selector import QuestionPrompt, SelectItem, select_question, select_questions


def test_select_question_returns_none_without_tty(monkeypatch: MonkeyPatch) -> None:
    class _NoTTY:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", _NoTTY())
    monkeypatch.setattr(sys, "stdout", _NoTTY())

    result = select_question(
        message="Pick",
        items=[
            SelectItem(title=[("", "1. A\n")], value="a", search_text="a"),
            SelectItem(title=[("", "2. B\n")], value="b", search_text="b"),
        ],
        multi_select=True,
    )
    assert result is None


def test_select_questions_returns_none_without_tty(monkeypatch: MonkeyPatch) -> None:
    class _NoTTY:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", _NoTTY())
    monkeypatch.setattr(sys, "stdout", _NoTTY())

    result = select_questions(
        questions=[
            QuestionPrompt(
                header="H1",
                message="Pick",
                items=[
                    SelectItem(title=[("", "1. A\n")], value="a", search_text="a"),
                    SelectItem(title=[("", "2. B\n")], value="b", search_text="b"),
                ],
                multi_select=True,
            )
        ]
    )
    assert result is None
