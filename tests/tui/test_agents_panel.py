import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.styles import Attrs

from klaude_code.protocol.models.session_status import SessionAttention, SessionStatus
from klaude_code.tui.agents_panel import AgentPanelSession, AgentsPanel, AgentsPanelResult, run_agents_panel


def session(
    id: str,
    category: str = "idle",
    *,
    directory: str = "/work/project",
    updated: float = 1,
    **kwargs: object,
) -> AgentPanelSession:
    return AgentPanelSession.model_validate(
        {"id": id, "status": {"category": category}, "work_dir": directory, "updated_at": updated, **kwargs}
    )


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


def test_project_paths_shorten_home_without_changing_search_or_grouping(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.tui.components import common

    home = Path("/Users/dev")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    directory = str(home / "code/project")
    monkeypatch.setattr(common, "active_work_dir", lambda: Path(directory))
    assert common.shorten_path(directory) == "."
    assert common.shorten_path(directory, relative_to_workspace=False) == "~/code/project"

    async def fetch() -> list[AgentPanelSession]:
        return [session("a", directory=directory), session("b", directory="/Users/developer/project")]

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, current_dir=directory, input=pipe, output=DummyOutput())
            await panel.refresh()
            text = "".join(text for _, text in panel._list_text(100))
            assert "~/code/project" in text
            assert "/Users/developer/project" in text
            assert "project: ~/code/project" in "".join(text for _, text in panel._detail_text())
            assert next(iter(panel.groups)) == directory
            panel.query = directory
            assert [row.id for row in panel.visible_sessions] == ["a"]

    asyncio.run(check())


def test_updated_time_calendar_boundaries() -> None:
    now = datetime(2026, 10, 20, 12, 30)
    for updated, label in [
        (now, "now"),
        (now + timedelta(minutes=5), "now"),
        (now - timedelta(minutes=5), "5m ago"),
        (now - timedelta(hours=2), "2h ago"),
        (datetime(2026, 10, 19, 23, 59), "yesterday"),
        (datetime(2026, 10, 18), "oct 18"),
        (datetime(2025, 10, 18), "oct 18 2025"),
    ]:
        assert AgentsPanel._updated_label(updated.timestamp(), now) == label
    assert AgentsPanel._updated_label(datetime(2025, 12, 31, 23, 59).timestamp(), datetime(2026, 1, 1)) == "yesterday"


@pytest.mark.parametrize("width", [1, 3, 4, 12, 24, 40, 80])
def test_list_reserves_display_cells_for_time_and_recomputes_on_refresh(
    width: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from prompt_toolkit.utils import get_cwidth

    from klaude_code.tui import agents_panel

    class Clock(datetime):
        current = datetime(2026, 10, 20, 12)

        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return cls.current

    monkeypatch.setattr(agents_panel, "datetime", Clock)
    updated = Clock.current.timestamp()

    async def fetch() -> list[AgentPanelSession]:
        return [session("a", title="中文标题与 English " * 20, updated=updated)]

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            await panel.refresh()
            fragments = panel._list_text(width)
            lines = "".join(text for _, text in fragments).splitlines()
            assert all(get_cwidth(line) <= width for line in lines)
            assert get_cwidth(lines[1]) == width
            if width >= 12:
                assert lines[1].endswith("now")
                assert any(style == "class:metadata.footer" and "now" in text for style, text in fragments)
                Clock.current += timedelta(minutes=5)
                await panel.refresh()
                assert "".join(text for _, text in panel._list_text(width)).splitlines()[1].endswith("5m ago")
                assert "updated: 2026-10-20 12:00" in "".join(text for _, text in panel._detail_text())
            assert not any("reverse" in style for style, _ in fragments)

    asyncio.run(check())


def test_groups_priority_counts_and_search_exclude_children() -> None:
    async def fetch() -> list[AgentPanelSession]:
        return [
            session("idle", updated=100),
            session("working-old", "working", updated=2),
            session("working-new", "working", updated=3),
            session(
                "attention",
                status={"category": "needs_you", "execution": "running"},
                name="Named agent",
            ),
            session("another", directory="/another"),
            session("child", directory="/child-only", parent_session_id="attention", agent_type="Explore"),
        ]

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            await panel.refresh()
            assert list(panel.groups) == ["/another", "/work/project"]
            assert [row.id for row in panel.groups["/work/project"]] == [
                "attention",
                "working-new",
                "working-old",
                "idle",
            ]
            assert panel.counts == {"all": 5, "needs_you": 1, "working": 2, "idle": 2}
            text = "".join(text for _, text in panel._list_text())
            assert "child" not in text and "Explore" not in text
            assert "Named agent" in text
            assert "! " in text
            panel.query = "NAMED"
            assert [row.id for row in panel.visible_sessions] == ["attention"]
            assert panel.counts["all"] == 5
            panel.query = "/another"
            assert [row.id for row in panel.visible_sessions] == ["another"]
            panel.state = "working"
            assert panel.visible_sessions == []
            assert session("fallback").label == "fallback"

    asyncio.run(check())


@pytest.mark.parametrize("columns", [40, 80, 100, 120, 180])
def test_split_width_does_not_change_when_recent_reply_loads(columns: int) -> None:
    class TerminalOutput(DummyOutput):
        def get_size(self) -> Size:
            return Size(rows=24, columns=columns)

    async def fetch() -> list[AgentPanelSession]:
        return [session("a")]

    async def check() -> None:
        release = asyncio.Event()

        async def load(id: str) -> str:
            await release.wait()
            return "REPLY-LOADED " + "long reply " * 1000

        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, load_output=load, input=pipe, output=TerminalOutput())
            task = asyncio.create_task(panel.run())
            try:
                await until(lambda: panel.selected_id == "a" and panel.detail_window.render_info is not None)
                await until(
                    lambda: panel.app.renderer.last_rendered_screen is not None
                    and panel.app.renderer.last_rendered_screen.data_buffer[3][columns * 2 // 5 + 3].char == "a"
                )

                def widths() -> tuple[int, int]:
                    assert panel.list_window.render_info is not None and panel.detail_window.render_info is not None
                    return panel.list_window.render_info.window_width, panel.detail_window.render_info.window_width

                before = widths()
                assert before == (columns * 2 // 5, columns - columns * 2 // 5 - 3)
                screen = panel.app.renderer.last_rendered_screen
                assert screen is not None
                assert all(screen.data_buffer[2][column].char == " " for column in range(columns))
                assert screen.data_buffer[3][before[0]].char == " "
                assert screen.data_buffer[3][before[0] + 1].char == "│"
                assert screen.data_buffer[3][before[0] + 2].char == " "
                assert screen.data_buffer[3][before[0] + 3].char == "a"
                release.set()
                await until(lambda: "REPLY-LOADED" in panel.output_text)
                counter = panel.app.render_counter
                await until(lambda: panel.app.render_counter > counter)
                assert widths() == before
            finally:
                pipe.send_text("q")
                await asyncio.wait_for(task, 3)

    asyncio.run(check())


def test_refresh_preserves_selection_search_and_detail_position_and_marks_stale() -> None:
    snapshot = [session("a"), session("b", updated=2)]
    fail = False

    async def fetch() -> list[AgentPanelSession]:
        if fail:
            raise OSError("unavailable")
        return snapshot

    async def check() -> None:
        nonlocal snapshot, fail
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            await panel.refresh()
            panel.move(1)
            assert panel.selected_id == "a"
            panel.query = "/work"
            panel.detail_line = 8
            snapshot = [session("a", updated=100), session("b")]
            await panel.refresh()
            assert panel.selected_id == "a"
            assert panel.detail_line == 8
            assert panel.query == "/work"
            fail = True
            await panel.refresh()
            assert panel.selected_id == "a"
            assert panel.fetch_error
            assert "stale" in str(panel._footer())
            fail = False
            snapshot = [session("b")]
            await panel.refresh()
            assert panel.selected_id == "b"
            assert panel.detail_line == 0
            snapshot = []
            await panel.refresh()
            assert panel.selected is None
            assert not panel.fetch_error
            assert "no matching" in str(panel._list_text())

    asyncio.run(check())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_staged_loading_is_interactive_preserves_state_and_cancels_on_exit(outcome: str) -> None:
    async def check() -> None:
        local = [session(f"local{i}", updated=10 - i) for i in range(7)]
        full = [session("other", directory="/another"), *local]
        release = asyncio.Event()
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        calls = 0
        initial_calls = 0
        hold = False

        async def initial() -> list[AgentPanelSession]:
            nonlocal initial_calls
            initial_calls += 1
            return local

        async def fetch() -> list[AgentPanelSession]:
            nonlocal calls
            calls += 1
            entered.set()
            try:
                if calls == 1:
                    await release.wait()
                    if outcome == "failure":
                        raise OSError("offline")
                elif hold:
                    await asyncio.Future[None]()
                return full
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with create_pipe_input() as pipe:
            panel = AgentsPanel(
                fetch,
                initial_fetch_sessions=initial,
                current_dir="/work/project",
                input=pipe,
                output=DummyOutput(),
            )
            task = asyncio.create_task(panel.run())
            try:
                await asyncio.wait_for(entered.wait(), 3)
                assert panel.sessions == local and not panel.loading
                assert "loading other projects..." in str(panel._tabs())
                await panel.refresh()
                assert calls == 1
                pipe.send_text("jjjjj\r")
                await until(lambda: panel.selected_id == "local5")
                pipe.send_text("/local\r")
                await until(lambda: panel.query == "local" and not panel.searching)
                assert "/work/project" in panel._expanded_groups
                if outcome != "cancel":
                    release.set()
                    await until(lambda: not panel.loading_other_projects)
                    assert panel.selected_id == "local5"
                    assert panel.query == "local" and "/work/project" in panel._expanded_groups
                    assert panel.fetch_error == (outcome == "failure")
                    if outcome == "failure":
                        assert panel.sessions == local
                        await panel.refresh()
                    assert panel.sessions == full and not panel.fetch_error
                    assert initial_calls == 1
                    assert "loading other projects..." not in str(panel._tabs())
                    hold = True
                    entered.clear()
                    panel._spawn(panel.refresh())
                    await asyncio.wait_for(entered.wait(), 3)
                    assert panel.sessions == full
                    assert not panel.loading_other_projects
            finally:
                pipe.send_text("q")
                await asyncio.wait_for(task, 3)
            assert cancelled.is_set()
            assert not panel._tasks

    asyncio.run(check())


@pytest.mark.parametrize("initial_fails", [False, True])
def test_empty_or_failed_initial_fetch_still_loads_full_snapshot(initial_fails: bool) -> None:
    async def initial() -> list[AgentPanelSession]:
        if initial_fails:
            raise OSError("offline")
        return []

    async def fetch() -> list[AgentPanelSession]:
        return [session("other", directory="/other")]

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, initial_fetch_sessions=initial, input=pipe, output=DummyOutput())
            await panel.refresh()
            assert panel.selected_id == "other"
            assert not panel.fetch_error and not panel.loading_other_projects

    asyncio.run(check())


@pytest.mark.parametrize("key,action", [("q", None), ("\x03", None), ("\x1b", None), ("\r", "attach"), ("p", "peek")])
def test_pipe_smoke_exit_attach_and_peek(key: str, action: Literal["attach", "peek"] | None) -> None:
    async def fetch() -> list[AgentPanelSession]:
        return [session("selected", name="A session")]

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await until(lambda: panel.selected_id == "selected" and panel.app.is_running)
            pipe.send_text(key)
            result = await asyncio.wait_for(task, 3)
            assert result == (AgentsPanelResult(session_id="selected", action=action) if action else None)
            assert not panel._tasks

    asyncio.run(check())


@pytest.mark.parametrize("remove_selected", [False, True])
def test_pipe_cancel_unmatched_search_restores_second_session(remove_selected: bool) -> None:
    snapshot = [session("a", updated=2), session("b")]

    async def fetch() -> list[AgentPanelSession]:
        return snapshot

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await until(lambda: panel.selected_id == "a" and panel.app.is_running)
            pipe.send_text("j")
            await until(lambda: panel.selected_id == "b")
            pipe.send_text("/missing")
            await until(lambda: panel.query == "missing")
            assert panel.selected_id is None
            if remove_selected:
                snapshot.pop()
                await panel.refresh()
            pipe.send_text("\x1b")
            await until(lambda: not panel.searching)
            assert panel.query == ""
            assert panel.selected_id == ("a" if remove_selected else "b")
            pipe.send_text("q")
            assert await asyncio.wait_for(task, 3) is None

    asyncio.run(check())


def test_pipe_tabs_search_navigation_and_refresh_preserve_selection() -> None:
    snapshot = [session("a", "working"), session("b", "working", updated=2), session("c")]
    calls = 0

    async def fetch() -> list[AgentPanelSession]:
        nonlocal calls
        calls += 1
        return snapshot

    async def check() -> None:
        nonlocal snapshot
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await until(lambda: panel.selected_id == "b" and panel.app.is_running)
            pipe.send_text("j")
            await until(lambda: panel.selected_id == "a")
            snapshot = [session("a", "working", updated=100), session("b", "working"), session("c")]
            await until(lambda: calls >= 2)
            assert panel.selected_id == "a"
            pipe.send_text("\t\t")  # All -> Needs you -> Working.
            await until(lambda: panel.state == "working")
            pipe.send_text("/b\r")
            await until(lambda: panel.query == "b" and not panel.searching)
            assert panel.selected_id == "b"
            pipe.send_text("/missing")
            await until(lambda: panel.query == "bmissing")
            assert panel.selected_id is None
            pipe.send_text("\x1b")
            await until(lambda: panel.query == "b" and not panel.searching)
            assert panel.selected_id == "b" and panel.app.is_running
            pipe.send_text("\x1b[D")
            await until(lambda: panel.state == "needs_you")
            assert panel.selected_id is None
            pipe.send_text("q")
            assert await asyncio.wait_for(task, 3) is None

    asyncio.run(check())


@pytest.mark.parametrize("switch_back", [False, True])
def test_late_cancel_suppressing_output_cannot_replace_new_selection(switch_back: bool) -> None:
    async def fetch() -> list[AgentPanelSession]:
        return [session("a", updated=2), session("b")]

    async def check() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        finished = asyncio.Event()
        a_calls = 0

        async def load(id: str) -> str:
            nonlocal a_calls
            if id == "a":
                a_calls += 1
            if id == "a" and a_calls == 1:
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                finished.set()
                return "OLD output"
            return "NEW output"

        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, load_output=load, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await started.wait()
            pipe.send_text("j")
            await until(lambda: panel.output_text == "NEW output")
            if switch_back:
                pipe.send_text("k")
                await until(lambda: a_calls == 2 and panel.output_text == "NEW output")
            release.set()
            await finished.wait()
            await asyncio.sleep(0)
            assert panel.selected_id == ("a" if switch_back else "b")
            assert panel.output_text == "NEW output"
            pipe.send_text("q")
            await asyncio.wait_for(task, 3)
            assert not panel._tasks

    asyncio.run(check())


def test_close_cancels_output_and_search_backspace_keeps_list_usable() -> None:
    async def check() -> None:
        output_started = asyncio.Event()
        output_cancelled = asyncio.Event()

        async def fetch() -> list[AgentPanelSession]:
            return [session("a"), session("b")]

        async def load(id: str) -> str:
            output_started.set()
            try:
                await asyncio.Future[None]()
            finally:
                output_cancelled.set()
            return ""

        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, load_output=load, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await output_started.wait()
            pipe.send_text("/b\x7f\r")
            await until(lambda: panel.query == "" and not panel.searching)
            pipe.send_text("j")
            await until(lambda: panel.selected_id == "b")
            pipe.send_text("q")
            await asyncio.wait_for(task, 3)
            assert output_cancelled.is_set()
            assert not panel._tasks

    asyncio.run(check())


def test_refresh_does_not_overlap_and_close_cancels_inflight_callbacks() -> None:
    async def check() -> None:
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        calls = 0

        async def fetch() -> list[AgentPanelSession]:
            nonlocal calls
            calls += 1
            entered.set()
            try:
                await asyncio.Future[None]()
            finally:
                cancelled.set()
            return []

        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await entered.wait()
            assert "loading" in str(panel._list_text())
            await panel.refresh()
            assert calls == 1
            pipe.send_text("q")
            await asyncio.wait_for(task, 3)
            assert cancelled.is_set()
            assert not panel._tasks

    asyncio.run(check())


def test_output_loads_only_on_selection_or_snapshot_change_and_retries_failure() -> None:
    async def check() -> None:
        row = session("a")
        calls = 0

        async def fetch() -> list[AgentPanelSession]:
            return [row]

        async def load(id: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("offline")
            return f"reply {calls}"

        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, load_output=load, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await until(lambda: panel.output_text == "reply 1")
            await panel.refresh()
            assert calls == 1
            row.updated_at = 2
            await panel.refresh()
            await until(lambda: "load failed" in panel.output_text)
            await panel.refresh()
            await until(lambda: panel.output_text == "reply 3")
            pipe.send_text("q")
            await asyncio.wait_for(task, 3)

    asyncio.run(check())


def test_explicit_controls_require_own_error_and_interrupt_confirmation() -> None:
    actions: list[tuple[str, str]] = []
    row = session("a", status={"category": "needs_you", "execution": "running"})
    row.status.attention = [SessionAttention(kind="error", code="failed", source_session_id="child")]

    async def fetch() -> list[AgentPanelSession]:
        return [row]

    async def control(id: str, action: str) -> None:
        actions.append((id, action))

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, control, input=pipe, output=DummyOutput())
            task = asyncio.create_task(panel.run())
            await until(lambda: panel.selected_id == "a" and panel.app.is_running)
            assert actions == []
            pipe.send_text("d")
            await until(lambda: "requires an error" in panel.notice)
            assert actions == []
            pipe.send_text("xn")
            await asyncio.sleep(0.05)
            assert actions == []
            pipe.send_text("\x18y")
            await until(lambda: actions == [("a", "interrupt")])
            row.status.attention[0].source_session_id = "a"
            pipe.send_text("d")
            await until(lambda: len(actions) == 2)
            assert actions[-1] == ("a", "dismiss")
            pipe.send_text("r")
            await until(lambda: len(actions) == 3)
            assert actions[-1] == ("a", "resume")
            pipe.send_text("q")
            await asyncio.wait_for(task, 3)

    asyncio.run(check())


def test_narrow_unicode_long_directory_detail_scrolling_and_output_bound() -> None:
    class ResizableOutput(DummyOutput):
        columns = 80

        def get_size(self) -> Size:
            return Size(rows=24, columns=self.columns)

    async def fetch() -> list[AgentPanelSession]:
        row = session("a", directory="/项目/" + "非常长的目录/" * 100, title="调查终端显示")
        row.status = SessionStatus.model_validate(
            {
                "category": "needs_you",
                "execution": "running",
                "attention": [
                    {"kind": "needs_input", "code": "approval", "source_session_id": "child", "message": "approve?"}
                ],
                "control": {"paused": True, "reason": "operator"},
                "continuation": {"automatic": False, "blocked_by": ["attention"]},
                "last_turn": {"id": "turn", "result": "interrupted"},
                "owned": {"active_agents": 2, "active_shells": 3},
            }
        )
        return [row]

    async def load(id: str) -> str:
        return "ignore\x1b[31m\n" * 1000 + "latest reply"

    async def check() -> None:
        output = ResizableOutput()
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, load_output=load, input=pipe, output=output)
            task = asyncio.create_task(panel.run())
            await until(lambda: "latest reply" in panel.output_text)
            detail = "".join(text for _, text in panel._detail_text())
            assert "project: /项目/" in detail
            assert "source: child" in detail and "approve?" in detail
            assert "execution: running" in detail and "control reason: operator" in detail
            assert "automatic continuation: not allowed" in detail
            assert "interrupted" in detail and "2 agents / 3 shells" in detail
            assert len(panel.output_text) <= 16000
            assert len(panel.output_text.splitlines()) <= 120
            assert "\x1b" not in panel.output_text
            await until(
                lambda: panel.detail_window.render_info is not None
                and panel.detail_window.render_info.content_height > 1
            )
            pipe.send_text("\x1b[6~")
            await until(lambda: panel.detail_line > 0)
            output.columns = 120
            panel.app.invalidate()
            await asyncio.sleep(0.05)
            output.columns = 40
            panel.app.invalidate()
            pipe.send_text("\r")
            assert await asyncio.wait_for(task, 3) == AgentsPanelResult(session_id="a", action="attach")

    asyncio.run(check())


def test_initial_fetch_failure_and_entrypoint() -> None:
    async def check() -> None:
        entered = asyncio.Event()

        async def fetch() -> list[AgentPanelSession]:
            entered.set()
            raise OSError("offline")

        with create_pipe_input() as pipe:
            task = asyncio.create_task(
                run_agents_panel(fetch, initial_state="needs_you", input=pipe, output=DummyOutput())
            )
            await entered.wait()
            pipe.send_text("q")
            assert await asyncio.wait_for(task, 3) is None

    asyncio.run(check())


@pytest.mark.parametrize("columns", [80, 120])
@pytest.mark.parametrize("paragraph", ["long text " * 500, "界" * 7000])
def test_paging_reveals_the_end_of_one_wrapped_paragraph(columns: int, paragraph: str) -> None:
    class TerminalOutput(DummyOutput):
        def get_size(self) -> Size:
            return Size(rows=24, columns=columns)

    async def fetch() -> list[AgentPanelSession]:
        return [session("a")]

    async def load(id: str) -> str:
        return "BEGIN-PARAGRAPH " + paragraph + " END-PARAGRAPH"

    async def check() -> None:
        with create_pipe_input() as pipe:
            panel = AgentsPanel(fetch, load_output=load, input=pipe, output=TerminalOutput())
            task = asyncio.create_task(panel.run())

            def visible_text() -> str:
                screen = panel.app.renderer.last_rendered_screen
                if screen is None:
                    return ""
                return "\n".join("".join(screen.data_buffer[y][x].char for x in range(columns)) for y in range(24))

            try:
                await until(lambda: "END-PARAGRAPH" in panel.output_text)
                assert "END-PARAGRAPH" not in visible_text()
                for _ in range(120):
                    pipe.send_text("\x1b[6~")
                    await asyncio.sleep(0.025)
                    if "END-PARAGRAPH" in visible_text():
                        break
                assert "END-PARAGRAPH" in visible_text()
                for _ in range(120):
                    pipe.send_text("\x1b[5~")
                    await asyncio.sleep(0.025)
                    if panel.detail_line == 0:
                        break
                assert panel.detail_line == 0
                await until(lambda: "model:" in visible_text())
            finally:
                pipe.send_text("q")
                await asyncio.wait_for(task, 3)

    asyncio.run(check())


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_detail_hierarchy_preserves_theme_styles_after_wrapping(theme: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.tui.components.rich.theme import DARK_PALETTE, LIGHT_PALETTE
    from klaude_code.tui.input import pt_theme

    monkeypatch.setattr(pt_theme, "_theme_name", theme)
    monkeypatch.setattr(pt_theme, "_configured", True)
    palette = LIGHT_PALETTE if theme == "light" else DARK_PALETTE

    async def fetch() -> list[AgentPanelSession]:
        return []

    async def load(id: str) -> str:
        return "Latest reply"

    with create_pipe_input() as pipe:
        panel = AgentsPanel(fetch, load_output=load, input=pipe, output=DummyOutput())
        panel.sessions = [
            session(
                "a",
                title="Readable title",
                model="test-model",
                status={
                    "category": "needs_you",
                    "execution": "running",
                    "attention": [
                        {"kind": "error", "code": "failed", "source_session_id": "a", "message": "Operation failed"}
                    ],
                },
            )
        ]
        panel.selected_id = "a"
        panel.output_text = "Latest reply"
        fragments = panel._detail_text(width=31)

        def attrs_for(value: str) -> Attrs:
            style = next(style for style, text in fragments if value in text)
            return pt_theme.get_base_style().get_attrs_for_style_str(style)

        assert not attrs_for("Readable title").bold
        assert attrs_for("Readable title").color == palette.cyan.lstrip("#")
        assert attrs_for("/work/project").color == palette.cyan.lstrip("#")
        assert not attrs_for("/work/project").bold
        assert not attrs_for("test-model").bold
        assert attrs_for("Operation failed").color == palette.red.lstrip("#")
        assert attrs_for("model:").color == palette.grey1.lstrip("#")
        assert attrs_for("recent reply").bold
        assert not attrs_for("Latest reply").bold
        rendered = "".join(text for _, text in fragments)
        assert rendered.index("recent reply") < rendered.index("needs your attention")
        assert rendered.index("recent reply") < rendered.index("runtime")
        panel.sessions.extend([session("b", title="Another title"), session("c", "working", title="Working title")])
        fragments = panel._list_text(width=80)
        assert attrs_for("/work/project").color == palette.cyan.lstrip("#")
        assert not attrs_for("/work/project").bold
        assert attrs_for("Readable title").color == palette.green.lstrip("#")
        assert attrs_for("Another title").color == palette.cyan.lstrip("#")
        assert not attrs_for("Another title").bold
        assert not attrs_for("Readable title").bold
        assert attrs_for("needs you").bold
        assert attrs_for("needs you").color == palette.yellow.lstrip("#")
        assert attrs_for("working ·").color == palette.green.lstrip("#")
        assert not attrs_for("working ·").bold
        assert attrs_for("idle ·").color == palette.grey2.lstrip("#")
        assert not attrs_for("idle ·").bold
        footer = panel._footer()
        assert len(footer) == 1 and footer[0][0] == "class:meta"
        assert "\n" not in footer[0][1]
        assert not any(pt_theme.get_base_style().get_attrs_for_style_str(style).reverse for style, _ in fragments)
        tabs = panel._tabs()
        assert tabs[1] == ("class:text", " ")
        active_style = next(style for style, text in tabs if "all" in text)
        assert active_style == "class:question_tab_active"
        assert pt_theme.get_base_style().get_attrs_for_style_str(active_style).reverse
