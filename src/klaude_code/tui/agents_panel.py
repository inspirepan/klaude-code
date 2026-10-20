"""Standalone terminal session browser; transport and attach live outside the panel."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Literal

from prompt_toolkit.application import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import DynamicContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.output import Output
from prompt_toolkit.output.color_depth import ColorDepth
from prompt_toolkit.output.defaults import create_output
from pydantic import BaseModel
from rich import get_console
from rich.text import Text

from klaude_code.protocol.models.session_status import SessionStatus
from klaude_code.tui.input.pt_theme import get_base_style

type PanelState = Literal["needs_you", "working", "idle", "all"]
type ControlAction = Literal["resume", "dismiss", "interrupt"]
type FetchSessions = Callable[[], Awaitable[list["AgentPanelSession"]]]
type ControlSession = Callable[[str, ControlAction], Awaitable[None]]
type LoadOutput = Callable[[str], Awaitable[str]]


class AgentPanelSession(BaseModel):
    id: str
    status: SessionStatus
    work_dir: str
    title: str | None = None
    name: str | None = None
    model: str | None = None
    updated_at: float
    activity: str | None = None
    parent_session_id: str | None = None
    agent_type: str | None = None

    @property
    def label(self) -> str:
        return self.title or self.name or self.agent_type or self.id


class AgentsPanelResult(BaseModel):
    session_id: str
    action: Literal["attach", "peek"]


class _DetailControl(FormattedTextControl):
    def __init__(
        self, get_text: Callable[[int], list[tuple[str, str]]], get_cursor_position: Callable[[], Point]
    ) -> None:
        super().__init__(get_cursor_position=get_cursor_position)
        self._get_text = get_text

    def create_content(self, width: int, height: int | None) -> UIContent:
        self.text = self._get_text(max(1, width))
        return super().create_content(width, height)


class AgentsPanel:
    states: tuple[PanelState, ...] = ("needs_you", "working", "idle", "all")
    labels = ("Needs you", "Working", "Idle", "All")

    def __init__(
        self,
        fetch_sessions: FetchSessions,
        control_session: ControlSession | None = None,
        load_output: LoadOutput | None = None,
        *,
        initial_state: PanelState = "all",
        input: Input | None = None,
        output: Output | None = None,
    ) -> None:
        self.fetch_sessions = fetch_sessions
        self.control_session = control_session
        self.load_output = load_output
        self.state = initial_state
        self.sessions: list[AgentPanelSession] = []
        self.selected_id: str | None = None
        self._selected_group: str | None = None
        self._expanded_groups: set[str] = set()
        self.query = ""
        self.searching = False
        self.loading = True
        self.fetch_error = False
        self.notice = ""
        self.confirm_interrupt: str | None = None
        self.output_text = ""
        self.detail_line = 0
        self._generation = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._output_task: asyncio.Task[None] | None = None
        self._output_version: tuple[str, float] | None = None
        self._control_task: asyncio.Task[None] | None = None
        self._refresh_lock = asyncio.Lock()
        self._closed = False
        self._terminal_output = output or create_output()

        self.list_control = FormattedTextControl(self._list_text, get_cursor_position=self._list_cursor, focusable=True)
        self.list_window = Window(
            self.list_control,
            wrap_lines=False,
            always_hide_cursor=True,
            height=lambda: Dimension(min=3, preferred=max(3, self.app.output.get_size().rows // 3))
            if self._narrow()
            else Dimension(),
        )
        self.detail_window = Window(
            _DetailControl(self._detail_text, get_cursor_position=lambda: Point(0, self.detail_line)),
            wrap_lines=False,
            always_hide_cursor=True,
        )
        self.list_window.width = lambda: (
            Dimension() if self._narrow() else Dimension.exact(max(36, self.app.output.get_size().columns * 2 // 5))
        )
        wide = VSplit(
            [
                self.list_window,
                Window(width=1, char="│", style="class:lines"),
                Window(width=1),
                self.detail_window,
            ]
        )
        narrow = HSplit([self.list_window, Window(height=1, char="-", style="class:lines"), self.detail_window])
        layout = HSplit(
            [
                Window(FormattedTextControl(self._tabs), height=1),
                Window(FormattedTextControl(self._search_text), height=1),
                DynamicContainer(lambda: narrow if self._narrow() else wide),
                Window(FormattedTextControl(self._footer), height=lambda: 5 if self._narrow() else 3, wrap_lines=True),
            ]
        )
        self.app: Application[AgentsPanelResult | None] = Application(
            layout=Layout(layout, focused_element=self.list_control),
            key_bindings=self._bindings(),
            style=get_base_style(),
            full_screen=True,
            color_depth=ColorDepth.TRUE_COLOR,
            input=input,
            output=self._terminal_output,
        )

    @staticmethod
    def _clean(text: str) -> str:
        # Remote strings are plain text, never terminal escape sequences.
        return "".join(char for char in text if char in "\n\t" or (ord(char) >= 32 and ord(char) != 127))

    def _narrow(self) -> bool:
        return self._terminal_output.get_size().columns < 95

    @property
    def counts(self) -> dict[PanelState, int]:
        return {
            state: sum(state == "all" or row.status.category == state for row in self.sessions) for state in self.states
        }

    @property
    def groups(self) -> dict[str, list[AgentPanelSession]]:
        query = self.query.casefold().strip()
        groups: dict[str, list[AgentPanelSession]] = {}
        for row in self.sessions:
            if self.state != "all" and row.status.category != self.state:
                continue
            if (
                query
                and query
                not in " ".join(
                    (row.id, row.label, row.work_dir, row.model or "", row.activity or "", row.agent_type or "")
                ).casefold()
            ):
                continue
            groups.setdefault(row.work_dir, []).append(row)
        priority = {"needs_you": 0, "working": 1, "idle": 2}
        return {
            directory: sorted(rows, key=lambda row: (priority[row.status.category], -row.updated_at, row.id))
            for directory, rows in sorted(groups.items())
        }

    @property
    def visible_sessions(self) -> list[AgentPanelSession]:
        return [
            row
            for directory, rows in self.groups.items()
            for row in (rows if directory in self._expanded_groups else rows[:5])
        ]

    @property
    def _navigation(self) -> list[AgentPanelSession | str]:
        items: list[AgentPanelSession | str] = []
        for directory, rows in self.groups.items():
            items.extend(rows if directory in self._expanded_groups else rows[:5])
            if len(rows) > 5:
                items.append(directory)
        return items

    @property
    def selected(self) -> AgentPanelSession | None:
        return next((row for row in self.visible_sessions if row.id == self.selected_id), None)

    def _tabs(self) -> list[tuple[str, str]]:
        counts = self.counts
        return [
            ("class:question_tab_active" if self.state == state else "class:meta", f" {label} {counts[state]} ")
            for state, label in zip(self.states, self.labels, strict=True)
        ]

    def _search_text(self) -> list[tuple[str, str]]:
        suffix = " [Enter to finish]" if self.searching else " [/ search]"
        return [("class:search_input", f" / {self._clean(self.query)}{suffix}")]

    def _list_text(self) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        for directory, rows in self.groups.items():
            if lines:
                lines.append(("", "\n"))
            lines.append(("class:meta", f" {self._clean(directory).replace(chr(10), ' ')} ({len(rows)})\n"))
            expanded = directory in self._expanded_groups
            for row in rows if expanded else rows[:5]:
                chosen = row.id == self.selected_id
                label = " ".join(self._clean(row.label).split())
                category = self.labels[self.states.index(row.status.category)]
                if row.status.category == "needs_you" and row.status.execution != "none":
                    category += f" / {row.status.execution}"
                style = " reverse" if chosen else ""
                status_style = {"needs_you": "class:warning", "working": "class:highlighted", "idle": "class:meta"}
                lines.extend(
                    [
                        (style, f" {'>' if chosen else ' '} "),
                        (status_style[row.status.category] + style, f"{category:<9} "),
                        (style, f"{label}\n"),
                    ]
                )
            if len(rows) > 5:
                chosen = directory == self._selected_group
                label = "Show less" if expanded else f"Show more ({len(rows) - 5})"
                lines.append(("class:meta" + (" reverse" if chosen else ""), f" {'>' if chosen else ' '} {label}\n"))
        if not lines:
            message = (
                "Loading sessions..."
                if self.loading
                else "Sessions unavailable"
                if self.fetch_error
                else "No matching sessions"
                if self.query
                else "No sessions in this tab"
            )
            lines.append(("class:meta", f" {message}"))
        return lines

    def _list_cursor(self) -> Point:
        line = 0
        for index, (directory, rows) in enumerate(self.groups.items()):
            if index:
                line += 1
            line += 1
            for row in rows if directory in self._expanded_groups else rows[:5]:
                if row.id == self.selected_id:
                    return Point(0, line)
                line += 1
            if len(rows) > 5:
                if directory == self._selected_group:
                    return Point(0, line)
                line += 1
        return Point(0, 0)

    def _detail_text(self, width: int | None = None) -> list[tuple[str, str]]:
        row = self.selected
        if row is None:
            return [("class:meta", "Select a session to see details.")]
        status = row.status
        text = Text()

        def append(value: str, style: str = "") -> None:
            text.append(self._clean(value), style=style)

        def field(label: str, value: str, style: str = "") -> None:
            append(f"{label}: ", "class:meta")
            append(value + "\n", style)

        append("Session details\n\n", "class:meta bold")
        append(row.label + "\n", "class:accent.cyan bold")
        category_style = {
            "needs_you": "class:accent.yellow bold",
            "working": "class:accent.green bold",
            "idle": "class:meta",
        }[status.category]
        append(self.labels[self.states.index(status.category)], category_style)
        if status.execution != "none":
            append("  /  ", "class:metadata.footer")
            append(status.execution.replace("_", " "), "class:accent.green")
        append("\n\n")
        field("Model", row.model or "-", "class:accent.blue")
        field("Agent", row.agent_type or "main")
        append("\nProject\n", "class:meta")
        append(row.work_dir + "\n")

        if status.attention:
            append("\nNeeds your attention\n", "class:accent.yellow bold")
        for attention in status.attention:
            attention_style = {
                "error": "class:accent.red",
                "paused": "class:accent.yellow",
                "needs_input": "class:accent.cyan",
            }[attention.kind]
            append(attention.kind.replace("_", " ").capitalize(), attention_style + " bold")
            append(f"  {attention.code}\n", "class:meta")
            if attention.message:
                append(attention.message + "\n", attention_style)
            if attention.source_session_id != row.id:
                field("Source", attention.source_session_id, "class:meta")
            if attention.request_id:
                field("Request", attention.request_id, "class:meta")

        append("\nRecent reply\n", "bold")
        pending_output = self._output_task is not None and not self._output_task.done()
        append(
            self.output_text if self.load_output else "Output preview unavailable",
            "class:metadata.footer" if pending_output or not self.load_output else "",
        )
        append("\n\nRuntime\n", "class:meta bold")
        field("Session", row.id, "class:metadata.footer")
        if row.name:
            field("Name", row.name)
        field("Execution", status.execution)
        if row.activity:
            field("Activity", row.activity)
        field("Control", "paused" if status.control.paused else "not paused")
        if status.control.reason:
            field("Control reason", status.control.reason, "class:accent.yellow")
        field("Automatic continuation", "allowed" if status.continuation.automatic else "not allowed")
        if status.continuation.triggers:
            field("Triggers", ", ".join(status.continuation.triggers), "class:meta")
        if status.continuation.blocked_by:
            field("Blocked by", ", ".join(status.continuation.blocked_by), "class:accent.yellow")
        if status.last_turn:
            field("Last turn", status.last_turn.result)
            if status.last_turn.reason:
                field("Last turn reason", status.last_turn.reason, "class:meta")
        field("Owned", f"{status.owned.active_agents} agents / {status.owned.active_shells} shells", "class:meta")

        # Rich wraps display cells; non-overlapping spans keep PTK theme tokens intact.
        lines = text.wrap(get_console(), width, overflow="fold") if width is not None else text.split(allow_blank=True)
        if width is not None:
            self.detail_line = min(self.detail_line, max(0, len(lines) - 1))
        fragments: list[tuple[str, str]] = []
        for index, line in enumerate(lines):
            if index:
                fragments.append(("", "\n"))
            offset = 0
            for span in sorted(line.spans, key=lambda span: span.start):
                if span.start > offset:
                    fragments.append(("", line.plain[offset : span.start]))
                fragments.append((str(span.style), line.plain[span.start : span.end]))
                offset = span.end
            if offset < len(line):
                fragments.append(("", line.plain[offset:]))
        return fragments

    def _footer(self) -> list[tuple[str, str]]:
        if self.confirm_interrupt:
            return [("class:warning", f" Interrupt {self._clean(self.confirm_interrupt)}? y confirms; n/Esc cancels")]
        status = "STALE: refresh failed; keeping last snapshot. " if self.fetch_error else ""
        if self._control_task and not self._control_task.done():
            status += "Control pending. "
        hints = (
            " j/k rows | Tab tabs | / search\n"
            " Enter attach | p peek | q/Esc quit\n"
            " r resume | d dismiss | x interrupt\n"
            " PgUp/PgDn details"
            if self._narrow()
            else " Up/Down j/k · Left/Right Tab tabs · / search · Enter attach · p peek · r resume · d dismiss error · x interrupt · PgUp/PgDn details · q/Esc quit"
        )
        return [
            ("class:warning" if self.fetch_error else "class:meta", f" {status}{self._clean(self.notice)}\n"),
            ("class:meta", hints),
        ]

    def _spawn(self, awaitable: Coroutine[object, object, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(awaitable)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _reconcile(self, previous_index: int = 0) -> None:
        items = self._navigation
        if self._selected_group is not None and self._selected_group in items:
            self.app.invalidate()
            return
        if not any(isinstance(item, AgentPanelSession) and item.id == self.selected_id for item in items):
            target = items[min(previous_index, len(items) - 1)] if items else None
            self._select(
                target.id if isinstance(target, AgentPanelSession) else None,
                group=target if isinstance(target, str) else None,
            )
        self.app.invalidate()

    def _select(self, session_id: str | None, *, group: str | None = None) -> None:
        if session_id == self.selected_id and group == self._selected_group:
            return
        self.selected_id = session_id
        self._selected_group = group
        self._generation += 1
        self.detail_line = 0
        self.detail_window.vertical_scroll = 0
        self.confirm_interrupt = None
        self.output_text = "Loading recent reply..." if session_id else ""
        self._output_version = None
        if self._output_task:
            self._output_task.cancel()
            self._output_task = None

    def move(self, delta: int) -> None:
        items = self._navigation
        if not items:
            return
        index = next(
            (
                index
                for index, item in enumerate(items)
                if (item == self._selected_group if isinstance(item, str) else item.id == self.selected_id)
            ),
            0,
        )
        target = items[max(0, min(len(items) - 1, index + delta))]
        self._select(
            target.id if isinstance(target, AgentPanelSession) else None,
            group=target if isinstance(target, str) else None,
        )
        self._start_output()
        self.app.invalidate()

    def _start_output(self) -> None:
        row = self.selected
        if not self.load_output or row is None or self._closed:
            return
        if self._output_task and not self._output_task.done():
            return
        version = (row.id, row.updated_at)
        if self._output_version == version:
            return
        self._output_version = version
        self._output_task = self._spawn(self._read_output(row.id, self._generation))

    async def _read_output(self, session_id: str, generation: int) -> None:
        assert self.load_output is not None
        failed = False
        try:
            # The transport should fetch only a recent reply, not full history.
            text = await self.load_output(session_id)
            text = "\n".join(text[-16000:].splitlines()[-120:]) or "No recent reply"
        except Exception:
            text = "Recent reply unavailable (load failed)"
            failed = True
        if not self._closed and session_id == self.selected_id and generation == self._generation:
            self.output_text = self._clean(text)
            if failed:
                self._output_version = None
            self.app.invalidate()

    async def refresh(self) -> None:
        if self._refresh_lock.locked():
            return
        async with self._refresh_lock:
            try:
                snapshot = await self.fetch_sessions()
            except Exception:
                self.fetch_error = True
            else:
                index = next(
                    (
                        i
                        for i, item in enumerate(self._navigation)
                        if (item == self._selected_group if isinstance(item, str) else item.id == self.selected_id)
                    ),
                    0,
                )
                self.sessions = [row for row in snapshot if row.parent_session_id is None]
                self.fetch_error = False
                self._reconcile(index)
                self._start_output()
            finally:
                self.loading = False
                self.app.invalidate()

    async def _poll(self) -> None:
        while not self._closed:
            await self.refresh()
            await asyncio.sleep(1)

    async def _control(self, session_id: str, action: ControlAction) -> None:
        assert self.control_session is not None
        try:
            await self.control_session(session_id, action)
        except Exception:
            self.notice = f"{action} failed; no success confirmed"
        else:
            self.notice = f"{action} accepted for {session_id}"
            await self.refresh()
        self.app.invalidate()

    def _request_control(self, action: ControlAction) -> None:
        row = self.selected
        if row is None:
            return
        if not self.control_session:
            self.notice = "Session controls unavailable"
        elif self.fetch_error:
            self.notice = "Refresh required before controlling a stale session"
        elif self._control_task and not self._control_task.done():
            self.notice = "Wait for the pending control"
        elif action == "dismiss" and not any(
            item.kind == "error" and item.source_session_id == row.id for item in row.status.attention
        ):
            self.notice = "Dismiss requires an error on this session (not a child)"
        elif action == "interrupt":
            self.confirm_interrupt = row.id
        else:
            self._control_task = self._spawn(self._control(row.id, action))
        self.app.invalidate()

    def _bindings(self) -> KeyBindings:
        keys = KeyBindings()
        browsing = Condition(lambda: not self.searching and self.confirm_interrupt is None)
        searching = Condition(lambda: self.searching)
        confirming = Condition(lambda: self.confirm_interrupt is not None)

        @keys.add("c-c")
        @keys.add("q", filter=browsing)
        def quit_panel(event: KeyPressEvent) -> None:
            event.app.exit(result=None)

        @keys.add("escape", eager=True)
        def escape(event: KeyPressEvent) -> None:
            if self.confirm_interrupt:
                self.confirm_interrupt = None
            elif self.searching:
                self.searching = False
            else:
                event.app.exit(result=None)

        @keys.add("up", filter=browsing)
        @keys.add("k", filter=browsing)
        def up(event: KeyPressEvent) -> None:
            self.move(-1)

        @keys.add("down", filter=browsing)
        @keys.add("j", filter=browsing)
        def down(event: KeyPressEvent) -> None:
            self.move(1)

        @keys.add("left", filter=browsing)
        @keys.add("right", filter=browsing)
        @keys.add("tab", filter=browsing)
        @keys.add("s-tab", filter=browsing)
        def tab(event: KeyPressEvent) -> None:
            delta = -1 if event.key_sequence[0].key in {"left", "s-tab"} else 1
            self.state = self.states[(self.states.index(self.state) + delta) % len(self.states)]
            self._reconcile()
            self._start_output()

        @keys.add("/", filter=browsing)
        def search(event: KeyPressEvent) -> None:
            self.searching = True

        @keys.add("<any>", filter=searching)
        @keys.add("backspace", filter=searching)
        def search_char(event: KeyPressEvent) -> None:
            if event.key_sequence[0].key == "c-h":
                self.query = self.query[:-1]
            elif event.data.isprintable():
                self.query += event.data
            self._reconcile()
            self._start_output()

        @keys.add("enter", filter=searching)
        def search_done(event: KeyPressEvent) -> None:
            self.searching = False

        @keys.add("enter", filter=browsing)
        @keys.add("p", filter=browsing)
        def choose(event: KeyPressEvent) -> None:
            if self._selected_group is not None:
                if event.data == "p":
                    return
                directory = self._selected_group
                rows = self.groups.get(directory, [])
                if len(rows) <= 5:
                    self._reconcile()
                    return
                if directory in self._expanded_groups:
                    self._expanded_groups.remove(directory)
                    self._select(rows[4].id)
                else:
                    self._expanded_groups.add(directory)
                    self._select(rows[5].id)
                self._start_output()
                self.app.invalidate()
            elif self.selected_id:
                event.app.exit(
                    result=AgentsPanelResult(
                        session_id=self.selected_id,
                        action="peek" if event.data == "p" else "attach",
                    )
                )

        @keys.add("r", filter=browsing)
        @keys.add("d", filter=browsing)
        @keys.add("x", filter=browsing)
        @keys.add("c-x", filter=browsing)
        def control(event: KeyPressEvent) -> None:
            self._request_control("resume" if event.data == "r" else "dismiss" if event.data == "d" else "interrupt")

        @keys.add("y", filter=confirming)
        def confirm(event: KeyPressEvent) -> None:
            session_id = self.confirm_interrupt
            self.confirm_interrupt = None
            if session_id and session_id == self.selected_id and not self.fetch_error and self.control_session:
                self._control_task = self._spawn(self._control(session_id, "interrupt"))

        @keys.add("n", filter=confirming)
        def cancel(event: KeyPressEvent) -> None:
            self.confirm_interrupt = None

        @keys.add("pageup", filter=browsing)
        @keys.add("pagedown", filter=browsing)
        def scroll(event: KeyPressEvent) -> None:
            info = self.detail_window.render_info
            if info is None or info.window_width <= 0:
                return
            delta = max(1, info.window_height // 2)
            if event.key_sequence[0].key == "pageup":
                delta = -delta
            self.detail_line = max(0, min(info.content_height - 1, self.detail_line + delta))

        return keys

    async def run(self) -> AgentsPanelResult | None:
        def start() -> None:
            self._spawn(self._poll())

        try:
            return await self.app.run_async(pre_run=start)
        finally:
            self._closed = True
            self._generation += 1
            tasks = list(self._tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def run_agents_panel(
    fetch_sessions: FetchSessions,
    control_session: ControlSession | None = None,
    load_output: LoadOutput | None = None,
    initial_state: PanelState = "all",
    *,
    input: Input | None = None,
    output: Output | None = None,
) -> AgentsPanelResult | None:
    return await AgentsPanel(
        fetch_sessions,
        control_session,
        load_output,
        initial_state=initial_state,
        input=input,
        output=output,
    ).run()
