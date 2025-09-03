from typing import override

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from src.protocal.events import (
    AssistantMessageDeltaEvent,
    AssistantMessageEvent,
    Event,
    ResponseMetadataEvent,
    TaskFinishEvent,
    TaskStartEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
)
from src.ui.ui import Display


class StdoutDisplay(Display):
    def __init__(self):
        self.console: Console = Console()

    @override
    async def consume_event(self, event: Event) -> None:
        match event:
            case TaskStartEvent():
                self.console.print()
            case TaskFinishEvent():
                pass
            case ThinkingDeltaEvent() as item:
                self.console.print(Text(item.content, style="bright_black"), end="")
            case ThinkingEvent() as item:
                self.console.print()
                self.console.print()
            case AssistantMessageDeltaEvent() as item:
                self.console.print(Text(item.content, style="bold"), end="")
            case AssistantMessageEvent() as item:
                self.console.print()
            case ResponseMetadataEvent() as item:
                rule_text = ""
                if item.usage is not None:
                    rule_text = f"[bold]token usage[/bold] input:{item.usage.input_tokens} cached:{item.usage.cached_tokens} reasoning:{item.usage.reasoning_tokens} output:{item.usage.output_tokens}"
                self.console.print(
                    Rule(
                        Text.from_markup(rule_text, style="grey70"),
                        style="grey70",
                        align="right",
                        characters="⎯",
                    )
                )
            case _:
                self.console.print("[Event]", event.__class__.__name__, event)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
