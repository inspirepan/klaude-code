import asyncio
from collections.abc import Callable

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from klaude_code.tui.agents_panel import AgentPanelSession, AgentsPanel


def session(id: str, directory: str = "/a", updated: float = 0, **kwargs: object) -> AgentPanelSession:
    return AgentPanelSession.model_validate(
        {"id": id, "work_dir": directory, "updated_at": updated, "status": {"category": "idle"}, **kwargs}
    )


def projects() -> list[AgentPanelSession]:
    return [session(f"{group}{index}", f"/{group}", 10 - index) for group in ("a", "b") for index in range(8)]


def test_current_project_first_and_refresh_does_not_displace_hidden_selection() -> None:
    snapshot = [*projects(), session("current", "/z", 0)]

    async def fetch() -> list[AgentPanelSession]:
        return snapshot

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, current_dir="/z", input=pipe, output=DummyOutput())
            await panel.refresh()
            assert list(panel.groups) == ["/z", "/a", "/b"]
            assert panel.selected_id == "current"
            assert " /z (1) · current" in "".join(text for _, text in panel._list_text())
            panel._select("a4")
            snapshot.extend(session(f"new{i}", "/a", 100 + i) for i in range(6))
            await panel.refresh()
            assert panel.selected_id == "a4"
            assert panel.selected is not None
            assert "/a" in panel._expanded_groups

    asyncio.run(check())


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("remove_group", [False, True])
def test_pipe_cancel_unmatched_search_restores_group_or_falls_back(remove_group: bool) -> None:
    snapshot = projects()

    async def fetch() -> list[AgentPanelSession]:
        return snapshot

    async def check() -> None:
        nonlocal snapshot
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await until(lambda: panel.selected_id == "a0" and panel.app.is_running)
            pipe.send_text("j" * 5)
            await until(lambda: panel._selected_group == "/a")
            pipe.send_text("/missing")
            await until(lambda: panel.query == "missing")
            assert panel.selected_id is None and panel._selected_group is None
            if remove_group:
                snapshot = [row for row in snapshot if row.work_dir != "/a"]
                await panel.refresh()
            pipe.send_text("\x1b")
            await until(lambda: not panel.searching)
            assert panel.query == ""
            assert panel._selected_group == (None if remove_group else "/a")
            assert panel.selected_id == ("b0" if remove_group else None)
            pipe.send_text("q")
            assert await asyncio.wait_for(task, 3) is None

    asyncio.run(check())


def test_groups_cap_counts_priority_spacing_and_cursor() -> None:
    async def fetch() -> list[AgentPanelSession]:
        return [
            *projects(),
            session("attention", status={"category": "needs_you"}),
            session("working", status={"category": "working"}),
            session("child", "/child", parent_session_id="a0"),
        ]

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            await panel.refresh()
            assert [row.id for row in panel.visible_sessions] == [
                "attention",
                "working",
                "a0",
                "a1",
                "a2",
                "b0",
                "b1",
                "b2",
                "b3",
                "b4",
            ]
            assert panel.counts == {"all": 18, "needs_you": 1, "working": 1, "idle": 16}
            text = "\n".join(line.rstrip() for line in "".join(text for _, text in panel._list_text()).split("\n"))
            assert "show more (5)\n\n /b (8)\n" in text
            assert "show more (3)" in text
            assert "child" not in text
            assert "a3" not in text and "b5" not in text
            for index in range(len(panel._navigation)):
                lines = "".join(text for _, text in panel._list_text()).splitlines()
                cursor = panel._list_cursor()
                assert lines[cursor.y].startswith(" > ")
                if panel._selected_group:
                    assert "show more" in lines[cursor.y]
                    assert panel.selected_id is None and panel.selected is None
                if index < len(panel._navigation) - 1:
                    panel.move(1)
            assert panel._list_cursor().y == 14

    asyncio.run(check())


def test_refresh_deleted_selection_uses_navigation_index_including_group_footer() -> None:
    snapshot = projects()

    async def fetch() -> list[AgentPanelSession]:
        return snapshot

    async def check() -> None:
        nonlocal snapshot
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            await panel.refresh()
            panel.move(6)
            assert panel.selected_id == "b0"
            snapshot = [row for row in snapshot if row.id != "b0"]
            await panel.refresh()
            assert panel.selected_id == "b1" and panel._selected_group is None

    asyncio.run(check())


def test_pipe_more_expand_first_hidden_refresh_and_less() -> None:
    snapshot = projects()

    async def fetch() -> list[AgentPanelSession]:
        return snapshot

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            try:
                await until(lambda: panel.selected_id == "a0" and panel.app.is_running)
                pipe.send_text("jjjjj")
                await until(lambda: panel._selected_group == "/a")
                await panel.refresh()
                assert panel._selected_group == "/a" and panel.selected_id is None
                pipe.send_text("\r")
                await until(lambda: panel.selected_id == "a5")
                assert panel._expanded_groups == {"/a"}
                assert [row.id for row in panel.visible_sessions] == [
                    *[f"a{index}" for index in range(8)],
                    *[f"b{index}" for index in range(5)],
                ]
                await panel.refresh()
                assert panel.selected_id == "a5" and len(panel.visible_sessions) == 13
                pipe.send_text("jjj")
                await until(lambda: panel._selected_group == "/a")
                assert "show less" in "".join(text for _, text in panel._list_text())
                await panel.refresh()
                assert panel._selected_group == "/a"
                pipe.send_text("\x1b[B")
                await until(lambda: panel.selected_id == "b0")
                pipe.send_text("\x1b[A")
                await until(lambda: panel._selected_group == "/a")
                pipe.send_text("\r")
                await until(lambda: panel.selected_id == "a4")
                assert not panel._expanded_groups
                assert len(panel.visible_sessions) == 10
            finally:
                pipe.send_text("q")
                assert await asyncio.wait_for(task, 3) is None

    asyncio.run(check())


def test_pipe_footer_ignores_session_actions_search_tabs_and_deleted_group() -> None:
    snapshot = projects()
    actions: list[tuple[str, str]] = []

    async def fetch() -> list[AgentPanelSession]:
        return snapshot

    async def control(id: str, action: str) -> None:
        actions.append((id, action))

    async def check() -> None:
        nonlocal snapshot
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, control, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            try:
                await until(lambda: panel.selected_id == "a0" and panel.app.is_running)
                pipe.send_text("jjjjjprdx\x18")
                await until(lambda: panel._selected_group == "/a")
                pipe.send_text("/a\r")
                await until(lambda: panel.query == "a" and not panel.searching)
                assert not task.done() and actions == [] and panel.confirm_interrupt is None
                assert panel._selected_group == "/a"
                pipe.send_text("\t")
                await until(lambda: panel.state == "needs_you")
                assert panel.selected is None and panel._selected_group is None
                pipe.send_text("\t\t")
                await until(lambda: panel.state == "idle" and panel.selected_id == "a0")
                pipe.send_text("jjjjj")
                await until(lambda: panel._selected_group == "/a")
                snapshot = [row for row in snapshot if row.work_dir == "/b"]
                await panel.refresh()
                assert panel.selected_id is None and panel._selected_group is None
                assert "no matching sessions" in "".join(text for _, text in panel._list_text())
                assert panel.counts["all"] == 8
                pipe.send_text("/\x7f\r")
                await until(lambda: panel.query == "" and not panel.searching)
                assert panel.selected_id == "b0"
                pipe.send_text("jjjjj")
                await until(lambda: panel._selected_group == "/b")
                snapshot = [session("new", "/c")]
                await panel.refresh()
                assert panel.selected_id == "new" and panel._selected_group is None
                snapshot = []
                await panel.refresh()
                assert panel.selected_id is None and panel._selected_group is None
            finally:
                pipe.send_text("q")
                assert await asyncio.wait_for(task, 3) is None

    asyncio.run(check())
