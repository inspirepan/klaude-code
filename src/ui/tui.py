from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static, Log

from src.protocal.events import (
    AssistantMessageDeltaEvent,
    AssistantMessageEvent,
    EndEvent,
    Event,
    ResponseMetadataEvent,
    TaskFinishEvent,
    TaskStartEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
)
from src.ui.ui import Display
from .input import InputProvider


class ChatApp(App):
    CSS = """
    Screen { layout: vertical; }
    #log { height: 1fr; }
    #stream { height: 3; color: grey70; }
    #input { height: 3; }
    """

    def __init__(self, event_q: asyncio.Queue[Event], input_q: asyncio.Queue[str]):
        super().__init__()
        self.event_q = event_q
        self.input_q = input_q
        self.log: Optional[Log] = None
        self.stream: Optional[Static] = None
        self._consumer_task: Optional[asyncio.Task] = None
        self._busy: bool = False
        self._stream_buf: str = ""

    def compose(self) -> ComposeResult:
        yield Vertical(
            Log(id="log"),
            Static("", id="stream"),
            Input(placeholder="Type message and press Enter", id="input"),
        )

    async def on_mount(self) -> None:
        self.log = self.query_one("#log", Log)
        self.stream = self.query_one("#stream", Static)
        input_widget = self.query_one("#input", Input)
        await input_widget.focus()
        # Start event consumer
        self._consumer_task = asyncio.create_task(self._consume_events())

    async def on_unmount(self) -> None:
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except Exception:
                pass

    async def _consume_events(self) -> None:
        while True:
            e = await self.event_q.get()
            try:
                match e:
                    case TaskStartEvent():
                        self._busy = True
                    case TaskFinishEvent():
                        self._busy = False
                    case ThinkingDeltaEvent() as ev:
                        self._stream_buf += ev.content
                        self._render_stream()
                    case ThinkingEvent() as ev:
                        self._append(ev.content, style="bright_black")
                        self._stream_buf = ""
                        self._render_stream()
                    case AssistantMessageDeltaEvent() as ev:
                        self._stream_buf += ev.content
                        self._render_stream()
                    case AssistantMessageEvent() as ev:
                        self._append(ev.content)
                        self._stream_buf = ""
                        self._render_stream()
                    case ResponseMetadataEvent() as ev:
                        # Optional: show usage line
                        if ev.usage is not None:
                            self._append(f"[metadata] {ev.usage}", style="grey70")
                    case EndEvent():
                        # EndEvent is handled by Display wrapper; ignore here
                        pass
                    case _:
                        # Fallback: append event class name
                        self._append(f"[event] {e.__class__.__name__}")
            finally:
                self.event_q.task_done()

    def _append(self, text: str, style: str = "") -> None:
        assert self.log is not None
        # Log doesn't support styles directly; keep plain text
        self.log.write_line(text)
        self.log.write_line("")  # spacing

    def _render_stream(self) -> None:
        assert self.stream is not None
        if self._stream_buf:
            self.stream.update(self._stream_buf)
        else:
            self.stream.update("")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if text:
            await self.input_q.put(text)


class TextualDisplay(Display):
    def __init__(self) -> None:
        self._event_q: asyncio.Queue[Event] = asyncio.Queue()
        self._input_q: asyncio.Queue[str] = asyncio.Queue()
        self._app = ChatApp(self._event_q, self._input_q)
        self._app_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        # run_async returns when the app is closed; keep as task
        self._app_task = asyncio.create_task(self._app.run_async())

    async def stop(self) -> None:
        # Request shutdown and await task
        await self._app.shutdown()
        if self._app_task:
            try:
                await self._app_task
            except Exception:
                pass

    async def consume_event(self, event: Event) -> None:
        await self._event_q.put(event)

    # Input provider support
    def get_input_queue(self) -> asyncio.Queue[str]:
        return self._input_q


class TextualInput(InputProvider):
    def __init__(self, display: TextualDisplay):
        self._q = display.get_input_queue()

    async def start(self) -> None:
        # Nothing to do; Textual app started by display
        pass

    async def stop(self) -> None:
        pass

    async def iter_inputs(self) -> AsyncIterator[str]:
        while True:
            line = await self._q.get()
            yield line
