from __future__ import annotations

import asyncio
from threading import Event
from typing import Any

import pytest
from prompt_toolkit.application import Application
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.styles import Style

from klaude_code.tui.terminal import selector
from klaude_code.tui.terminal.selector import SelectItem


def choices(*, unlocked: bool = False) -> list[SelectItem[str]]:
    return [
        SelectItem(title=[("", "Today\n")], value=None, search_text="", selectable=False),
        SelectItem(
            title=[("class:meta", "open session\n")], value="open", search_text="open session", selectable=unlocked
        ),
        SelectItem(title=[("", "saved session\n")], value="saved", search_text="saved session"),
    ]


def test_disabled_choices_remain_searchable_under_their_header() -> None:
    items = choices()
    assert selector._filter_items(items, "open") == ([0, 1], True)
    assert selector._filter_items(items, "saved") == ([0, 2], True)
    assert selector._filter_items(items, "no match") == ([], False)
    assert selector._coerce_pointed_at_to_selectable(items, [0, 1, 2], 0) == 2
    assert selector._move_pointed_at(items, [0, 1, 2], 2, 1) == 2


def test_keyboard_cannot_accept_disabled_match_and_refreshes_lease_before_accepting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(selector.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(selector.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(selector, "get_base_style", lambda: Style.from_dict({}))
    applications: list[Application[str | None]] = []
    unlocked = Event()
    calls: list[bool] = []

    def provide() -> list[SelectItem[str]]:
        calls.append(unlocked.is_set())
        return choices(unlocked=unlocked.is_set())

    async def eventually(predicate) -> None:
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    async def run() -> None:
        with create_pipe_input() as pipe:

            def application(**kwargs: Any) -> Application[str | None]:
                app = Application(input=pipe, output=DummyOutput(), **kwargs)
                applications.append(app)
                return app

            monkeypatch.setattr(selector, "Application", application)
            task = asyncio.create_task(
                asyncio.to_thread(
                    selector.select_one,
                    message="Resume",
                    items=provide(),
                    items_provider=provide,
                    initial_search_text="open",
                )
            )
            try:
                await eventually(lambda: applications and applications[0].is_running)
                before = len(calls)
                pipe.send_text("\r\t")
                await eventually(lambda: len(calls) >= before + 2)
                assert not task.done()
                unlocked.set()
                pipe.send_text("\r")
                assert await asyncio.wait_for(task, 3) == "open"
            finally:
                if not task.done():
                    pipe.send_text("\x03")
                    await asyncio.wait_for(task, 3)

    asyncio.run(run())
