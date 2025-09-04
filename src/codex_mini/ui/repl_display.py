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
    ToolCallResultEvent,
)
from codex_mini.ui.display_abc import Display
from codex_mini.ui.utils import format_number


class REPLDisplay(Display):
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
            case ToolCallResultEvent() as e:
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

    def truncate_diplay(self, text: str) -> str:
        lines = text.split("\n")
        if len(lines) > 20:
            return (
                "\n".join(lines[:20])
                + "\n... (more "
                + str(len(lines) - 20)
                + " lines are truncated)"
            )
        return text

    def display_tool_call_result(self, e: ToolCallResultEvent) -> None:
        self.console.print(
            Padding.indent(
                Text(
                    self.truncate_diplay(e.result),
                    style="grey50" if e.status == "success" else "red",
                ),
                level=2,
            )
        )

    def display_metadata(self, e: ResponseMetadataEvent) -> None:
        rule_text = f"[bold][cyan]{e.model_name}[/cyan][/bold]"
        if e.usage is not None:
            token_parts = [f"input:{format_number(e.usage.input_tokens)}"]
            if e.usage.cached_tokens > 0:
                token_parts.append(f"cached:{format_number(e.usage.cached_tokens)}")
            token_parts.append(f"output:{format_number(e.usage.output_tokens)}")
            if e.usage.reasoning_tokens > 0:
                token_parts.append(
                    f"reasoning:{format_number(e.usage.reasoning_tokens)}"
                )

            rule_text += f" · [bold]token[/bold] {' '.join(token_parts)}"
        self.console.print(
            Rule(
                Text.from_markup(rule_text, style="grey70"),
                style="grey70",
                align="right",
                characters="⎯",
            )
        )
