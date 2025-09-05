import json
from typing import override

from rich.console import Console
from rich.padding import Padding
from rich.rule import Rule
from rich.status import Status
from rich.text import Text

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
from codex_mini.ui.utils import format_number


class REPLDisplay(DisplayABC):
    def __init__(self):
        self.console: Console = Console()
        self.spinner: Status = Status("Thinking...", spinner="bouncingBall")

    @override
    async def consume_event(self, event: Event) -> None:
        match event:
            case TaskStartEvent():
                self.console.print()
                # self.spinner.start()
            case TaskFinishEvent():
                # self.spinner.stop()
                pass
            case ThinkingDeltaEvent() as e:
                self.console.print(Text(e.content, style="italic bright_black"), end="")
            case ThinkingEvent() as e:
                self.console.print("\n")
            case AssistantMessageDeltaEvent() as e:
                self.console.print(Text(e.content, style="bold"), end="")
            case AssistantMessageEvent() as e:
                self.console.print("\n")
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
        if e.usage is not None:
            cached_token_str = f"({format_number(e.usage.cached_tokens)} cached)" if e.usage.cached_tokens > 0 else ""
            reasoning_token_str = (
                f"({format_number(e.usage.reasoning_tokens)} reasoning)" if e.usage.reasoning_tokens > 0 else ""
            )
            rule_text += f" · [bold]token usage[/bold]: {format_number(e.usage.input_tokens)} input{cached_token_str}, {format_number(e.usage.output_tokens)} output{reasoning_token_str}"
        self.console.print(
            Rule(
                Text.from_markup(rule_text, style="bright_black"),
                style="bright_black",
                align="right",
                characters="-",
            )
        )
