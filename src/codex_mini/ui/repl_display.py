import json
from typing import override

from rich.console import Console
from rich.padding import Padding
from rich.rule import Rule
from rich.text import Text
from rich.theme import Theme

from codex_mini.protocol.events import (
    AssistantMessageDeltaEvent,
    AssistantMessageEvent,
    Event,
    ResponseMetadataEvent,
    TaskFinishEvent,
    TaskStartEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from codex_mini.ui.display_abc import DisplayABC
from codex_mini.ui.mdstream import MarkdownStream
from codex_mini.ui.utils import format_number

CODE_THEME = "solarized-light"
MARKDOWN_THEME = Theme(
    styles={
        "markdown.code": "medium_purple3",
        "markdown.h1.border": "gray70",
        "markdown.h3": "bold gray54",
        "markdown.h4": "bold gray70",
    }
)
THINKING_PREFIX = "✶ Thinking...\n\n"


class REPLDisplay(DisplayABC):
    def __init__(self):
        self.console: Console = Console()
        self.mdstream: MarkdownStream | None = None
        self.current_stream_text = ""

    @override
    async def consume_event(self, event: Event) -> None:
        match event:
            case TaskStartEvent():
                self.console.print()
            case TaskFinishEvent():
                pass
            case ThinkingDeltaEvent() as e:
                if len(self.current_stream_text) == 0:
                    self.current_stream_text = THINKING_PREFIX
                self.current_stream_text += e.content
                if self.mdstream is None:
                    self.mdstream = MarkdownStream(
                        mdargs={"style": "italic bright_black", "code_theme": CODE_THEME}, theme=MARKDOWN_THEME
                    )
                self.mdstream.update(self.current_stream_text.strip())
            case ThinkingEvent() as e:
                if self.mdstream is not None:
                    self.mdstream.update(THINKING_PREFIX + e.content.strip(), final=True)
                self.current_stream_text = ""
                self.mdstream = None
            case AssistantMessageDeltaEvent() as e:
                self.current_stream_text += e.content
                if self.mdstream is None:
                    self.mdstream = MarkdownStream(mdargs={"code_theme": CODE_THEME}, theme=MARKDOWN_THEME)
                self.mdstream.update(self.current_stream_text.strip())
            case AssistantMessageEvent() as e:
                if self.mdstream is not None:
                    self.mdstream.update(e.content.strip(), final=True)
                self.current_stream_text = ""
                self.mdstream = None
            case ResponseMetadataEvent() as e:
                self.display_metadata(e)
                self.console.print()
            case ToolCallEvent() as e:
                self.display_tool_call(e)
            case ToolResultEvent() as e:
                self.display_tool_call_result(e)
                self.console.print()
            case _:
                self.console.print("[Event]", event.__class__.__name__, event)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def render_tool_call_arguments(self, arguments: str) -> Text:
        if not arguments:
            return Text("")
        try:
            json_dict = json.loads(arguments)
            if len(json_dict) == 0:
                return Text("")
            if len(json_dict) == 1:
                return Text(str(next(iter(json_dict.values()))), "green")
            return Text(", ".join([f"{k}: {v}" for k, v in json_dict.items()]), "green")
        except json.JSONDecodeError:
            return Text(arguments)

    def display_tool_call(self, e: ToolCallEvent) -> None:
        self.console.print(
            Text.assemble(
                "⏵ ",
                (e.tool_name, "bold"),
                " ",
                self.render_tool_call_arguments(e.arguments),
            )
        )

    def truncate_display(self, text: str) -> str:
        lines = text.split("\n")
        if len(lines) > 20:
            return "\n".join(lines[:20]) + "\n... (more " + str(len(lines) - 20) + " lines are truncated)"
        return text

    def display_tool_call_result(self, e: ToolResultEvent) -> None:
        self.console.print(
            Padding.indent(
                Text(
                    self.truncate_display(e.result),
                    style="grey50" if e.status == "success" else "red",
                ),
                level=2,
            )
        )

    def display_metadata(self, e: ResponseMetadataEvent) -> None:
        rule_text = f"[bold]{e.model_name}[/bold]"
        if e.provider is not None:
            rule_text += f" · provider [bold]{e.provider.lower()}[/bold]"
        if e.usage is not None:
            cached_token_str = (
                f"([b]{format_number(e.usage.cached_tokens)}[/b] cached)" if e.usage.cached_tokens > 0 else ""
            )
            reasoning_token_str = (
                f"([b]{format_number(e.usage.reasoning_tokens)}[/b] reasoning)" if e.usage.reasoning_tokens > 0 else ""
            )
            rule_text += f" · token usage [b]{format_number(e.usage.input_tokens)}[/b] input {cached_token_str} [b]{format_number(e.usage.output_tokens)}[/b] output {reasoning_token_str}"
        self.console.print(
            Rule(
                Text.from_markup(rule_text, style="bright_black", overflow="fold"),
                style="bright_black",
                align="right",
                characters="-",
            )
        )
