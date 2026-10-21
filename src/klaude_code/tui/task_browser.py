"""Embedded task list and output preview, sharing the prompt's input owner."""

from collections.abc import Callable

from prompt_toolkit.application import get_app
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import ConditionalContainer, DynamicContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from rich import get_console
from rich.text import Text

from klaude_code.protocol.background_task import ACTIVE_TASK_STATUSES, BackgroundTaskSnapshot
from klaude_code.tui.terminal.selector import SelectItem, SelectOverlay


class TaskBrowser(SelectOverlay[str]):
    tabs = ("all", "active", "needs attention", "finished")

    def __init__(
        self, *, on_select: Callable[[str], None], on_cancel: Callable[[], None], get_reserved_rows: Callable[[], int]
    ) -> None:
        self.browsing = False
        self.tasks: list[BackgroundTaskSnapshot] = []
        self.attention: dict[str, str] = {}
        self.tab = "all"
        self.preview = ""
        self.preview_id: str | None = None
        self.detail_line = 0
        self.notice = ""
        super().__init__(on_select=on_select, on_cancel=on_cancel, get_reserved_rows=get_reserved_rows)

    @property
    def selected_id(self) -> str | None:
        indices, _ = self._get_visible_indices()
        return self._items[indices[min(self._pointed_at, len(indices) - 1)]].value if indices else None

    def _matches_tab(self, task: BackgroundTaskSnapshot, tab: str) -> bool:
        if tab == "active":
            return task.status in ACTIVE_TASK_STATUSES
        if tab == "needs attention":
            return task.ref.session_id in self.attention or task.status in {"failed", "lost", "timed_out"}
        if tab == "finished":
            return task.status not in ACTIVE_TASK_STATUSES
        return True

    def update(self, tasks: list[BackgroundTaskSnapshot], attention: dict[str, str]) -> None:
        selected = self.selected_id
        self.tasks, self.attention = tasks, attention
        self._items = []
        for task in tasks:
            if not self._matches_tab(task, self.tab):
                continue
            label = " ".join((task.description or (task.shell.command if task.shell else "Agent task")).split())
            status = attention.get(task.ref.session_id or "", task.status)
            label = "".join(char for char in label if ord(char) >= 32 and ord(char) != 127)
            metadata = f"{'Agent' if task.ref.kind == 'agent' else 'Bash'} · {status}"
            style = (
                "class:accent.yellow"
                if self._matches_tab(task, "needs attention")
                else "class:accent.green"
                if task.status in ACTIVE_TASK_STATUSES
                else "class:meta"
            )
            self._items.append(
                SelectItem(
                    title=[("", label + "\n"), (style, metadata + "\n")],
                    value=task.ref.task_id,
                    search_text=f"{label} {metadata} {task.ref.task_id}",
                )
            )
        indices, _ = self._get_visible_indices()
        self._pointed_at = next((i for i, idx in enumerate(indices) if self._items[idx].value == selected), 0)
        get_app().invalidate()

    def _build_key_bindings(self) -> KeyBindings:
        keys = super()._build_key_bindings()
        active = Condition(lambda: self.is_open and self.browsing)

        @keys.add("left", filter=active, eager=True)
        @keys.add("right", filter=active, eager=True)
        def change_tab(event: KeyPressEvent) -> None:
            delta = -1 if event.key_sequence[0].key == "left" else 1
            self.tab = self.tabs[(self.tabs.index(self.tab) + delta) % len(self.tabs)]
            self.update(self.tasks, self.attention)

        @keys.add("c-u", filter=active, eager=True)
        @keys.add("c-d", filter=active, eager=True)
        @keys.add("pageup", filter=active, eager=True)
        @keys.add("pagedown", filter=active, eager=True)
        def scroll(event: KeyPressEvent) -> None:
            info = self._preview_window.render_info
            if info is None:
                return
            delta = max(1, info.window_height // 2)
            if event.key_sequence[0].key in {"pageup", "c-u"}:
                delta = -delta
            self.detail_line = max(0, min(max(0, info.content_height - info.window_height), self.detail_line + delta))

        return keys

    def _build_layout(self) -> ConditionalContainer:
        fallback = super()._build_layout()
        assert self._search_buffer is not None

        def height() -> int:
            reserved = self._get_reserved_rows() if self._get_reserved_rows else 5
            return max(1, min(14, get_app().output.get_size().rows - reserved - 4))

        def tabs() -> list[tuple[str, str]]:
            return [
                (
                    "class:question_tab_active" if tab == self.tab else "class:question_tab_inactive",
                    f" {tab} {sum(self._matches_tab(task, tab) for task in self.tasks)} ",
                )
                for tab in self.tabs
            ]

        def rows() -> list[tuple[str, str]]:
            indices, _ = self._get_visible_indices()
            width = max(1, get_app().output.get_size().columns * 2 // 5 - 2)
            result: list[tuple[str, str]] = []
            for i, idx in enumerate(indices):
                for line, (style, text) in enumerate(self._items[idx].title):
                    value = Text(("> " if i == self._pointed_at and line == 0 else "  ") + text.rstrip("\n"))
                    value.truncate(width, overflow="ellipsis")
                    result.append(
                        ("class:highlighted bold" if i == self._pointed_at and line == 0 else style, value.plain + "\n")
                    )
            return result or [("class:meta", "No matching tasks")]

        def detail() -> str:
            if self.selected_id != self.preview_id:
                return "Loading output…" if self.selected_id else "Select a task to see output"
            width = max(1, get_app().output.get_size().columns - get_app().output.get_size().columns * 2 // 5 - 1)
            lines = Text(self.preview).wrap(get_console(), width, overflow="fold")
            info = self._preview_window.render_info
            viewport_height = info.window_height if info is not None else height()
            self.detail_line = min(self.detail_line, max(0, len(lines) - viewport_height))
            return "\n".join(line.plain for line in lines)

        listing = Window(
            FormattedTextControl(rows, get_cursor_position=lambda: Point(0, self._pointed_at * 2)),
            width=lambda: max(1, get_app().output.get_size().columns * 2 // 5),
            wrap_lines=False,
            always_hide_cursor=True,
        )
        preview = self._preview_window = Window(
            FormattedTextControl(detail, get_cursor_position=lambda: Point(0, self.detail_line)),
            get_vertical_scroll=lambda _: self.detail_line,
            wrap_lines=False,
            always_hide_cursor=True,
        )
        search = Window(BufferControl(buffer=self._search_buffer), height=1)
        body = HSplit(
            [
                Window(FormattedTextControl(tabs), height=1),
                VSplit([Window(FormattedTextControl(" / "), width=3), search], height=1),
                VSplit([listing, Window(width=1, char="│", style="class:lines"), preview], height=height),
                Window(
                    FormattedTextControl(lambda: self.notice or "↑/↓ to select · ←/→ to filter · enter to manage"),
                    height=1,
                ),
                Window(
                    FormattedTextControl("ctrl-u/d or pgup/pgdn to scroll output · esc to clear/quit"),
                    height=1,
                ),
            ]
        )
        # Both views use the same search buffer, so focus and drafts stay owned by the prompt.

        self._browser_search = search
        return ConditionalContainer(
            DynamicContainer(lambda: body if self.browsing else fallback), filter=Condition(lambda: self.is_open)
        )

    def open(self) -> None:
        super().open()
        if self.browsing:
            get_app().layout.focus(self._browser_search)
