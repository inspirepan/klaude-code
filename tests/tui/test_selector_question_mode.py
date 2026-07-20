from __future__ import annotations

import sys
from typing import Any

from _pytest.monkeypatch import MonkeyPatch

from klaude_code.tui.terminal import ask_user_question
from klaude_code.tui.terminal.ask_user_question import (
    _has_unconfirmed_edits,  # pyright: ignore[reportPrivateUsage]
    _normalize_question_selection,  # pyright: ignore[reportPrivateUsage]
    _should_imply_pointed_selection,  # pyright: ignore[reportPrivateUsage]
)
from klaude_code.tui.terminal.selector import (
    QuestionPrompt,
    QuestionSelectResult,
    SelectItem,
    select_question,
    select_questions,
)


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


def test_select_questions_marks_terminal_title_until_cancelled(monkeypatch: MonkeyPatch) -> None:
    class _TTY:
        def isatty(self) -> bool:
            return True

    calls: list[str] = []

    class _Renderer:
        cpr_not_supported_callback: Any = None

    class _Application:
        renderer = _Renderer()

        def __init__(self, **_: Any) -> None:
            pass

        def run(self) -> None:
            assert calls == ["set:❓"]
            return None

    monkeypatch.setattr(sys, "stdin", _TTY())
    monkeypatch.setattr(sys, "stdout", _TTY())
    monkeypatch.setattr(ask_user_question, "Application", _Application)
    monkeypatch.setattr(
        ask_user_question.terminal_title,
        "set_terminal_title_override",
        lambda prefix: calls.append(f"set:{prefix}"),
    )
    monkeypatch.setattr(
        ask_user_question.terminal_title,
        "clear_terminal_title_override",
        lambda: calls.append("clear"),
    )

    result = ask_user_question.select_questions(
        questions=[
            QuestionPrompt(
                header="H1",
                message="Pick",
                items=[SelectItem(title=[("", "1. A\n")], value="a", search_text="a")],
                multi_select=False,
            )
        ]
    )

    assert result is None
    assert calls == ["set:❓", "clear"]


def test_normalize_question_selection_single_select_other_overrides_previous_choice() -> None:
    question = QuestionPrompt(
        header="Role",
        message="Pick one",
        items=[
            SelectItem(title=[("", "1. A\n")], value="a", search_text="a"),
            SelectItem(title=[("", "2. B\n")], value="b", search_text="b"),
        ],
        multi_select=False,
        other_value="__other__",
    )

    result = _normalize_question_selection(question, ["a"], "custom")

    assert result == ["__other__"]


def test_normalize_question_selection_multi_select_appends_other() -> None:
    question = QuestionPrompt(
        header="Focus",
        message="Pick several",
        items=[
            SelectItem(title=[("", "1. A\n")], value="a", search_text="a"),
            SelectItem(title=[("", "2. B\n")], value="b", search_text="b"),
        ],
        multi_select=True,
        other_value="__other__",
    )

    result = _normalize_question_selection(question, ["a"], "custom")

    assert result == ["a", "__other__"]


def test_has_unconfirmed_edits_is_false_before_first_confirmation() -> None:
    question = QuestionPrompt(
        header="Role",
        message="Pick one",
        items=[
            SelectItem(title=[("", "1. A\n")], value="a", search_text="a"),
            SelectItem(title=[("", "2. B\n")], value="b", search_text="b"),
        ],
        multi_select=False,
        other_value="__other__",
    )

    confirmed: QuestionSelectResult[str] = QuestionSelectResult(selected_values=[], input_text="")
    draft: QuestionSelectResult[str] = QuestionSelectResult(selected_values=["b"], input_text="")

    assert _has_unconfirmed_edits(question, confirmed, draft, is_answered=False) is False


def test_has_unconfirmed_edits_is_true_after_confirmed_answer_changes() -> None:
    question = QuestionPrompt(
        header="Role",
        message="Pick one",
        items=[
            SelectItem(title=[("", "1. A\n")], value="a", search_text="a"),
            SelectItem(title=[("", "2. B\n")], value="b", search_text="b"),
        ],
        multi_select=False,
        other_value="__other__",
    )

    confirmed: QuestionSelectResult[str] = QuestionSelectResult(selected_values=["a"], input_text="")
    draft: QuestionSelectResult[str] = QuestionSelectResult(selected_values=["b"], input_text="")

    assert _has_unconfirmed_edits(question, confirmed, draft, is_answered=True) is True


def test_has_unconfirmed_edits_is_false_for_equivalent_other_with_whitespace() -> None:
    question = QuestionPrompt(
        header="Role",
        message="Pick one",
        items=[
            SelectItem(title=[("", "1. A\n")], value="a", search_text="a"),
            SelectItem(title=[("", "2. B\n")], value="b", search_text="b"),
        ],
        multi_select=False,
        other_value="__other__",
    )

    confirmed: QuestionSelectResult[str] = QuestionSelectResult(selected_values=["__other__"], input_text="custom")
    draft: QuestionSelectResult[str] = QuestionSelectResult(selected_values=["a"], input_text="custom   ")

    assert _has_unconfirmed_edits(question, confirmed, draft, is_answered=True) is False


def test_preview_question_does_not_imply_selection_from_focus() -> None:
    question = QuestionPrompt(
        header="Design",
        message="Pick one",
        items=[
            SelectItem(title=[("", "1. A\n")], value="a", search_text="a", markdown="# A"),
            SelectItem(title=[("", "2. B\n")], value="b", search_text="b", markdown="# B"),
        ],
        multi_select=False,
    )

    assert (
        _should_imply_pointed_selection(
            question,
            has_explicit_selection=False,
            pointed_at=0,
            on_input_row=False,
            on_submit_row=False,
        )
        is False
    )


def test_regular_single_select_still_implies_selection_from_focus() -> None:
    question = QuestionPrompt(
        header="Role",
        message="Pick one",
        items=[
            SelectItem(title=[("", "1. A\n")], value="a", search_text="a"),
            SelectItem(title=[("", "2. B\n")], value="b", search_text="b"),
        ],
        multi_select=False,
        other_value="__other__",
    )

    assert (
        _should_imply_pointed_selection(
            question,
            has_explicit_selection=False,
            pointed_at=1,
            on_input_row=False,
            on_submit_row=False,
        )
        is True
    )
