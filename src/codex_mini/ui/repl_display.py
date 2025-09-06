import json
import time
from typing import Literal, override

from rich.console import Console, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from codex_mini.protocol import events, model, tools
from codex_mini.ui.display_abc import DisplayABC
from codex_mini.ui.mdstream import MarkdownStream
from codex_mini.ui.utils import format_number

CODE_THEME = "solarized-light"
MARKDOWN_THEME = Theme(
    styles={
        "markdown.code": "medium_purple3",
        "markdown.h1.border": "gray70",
        "markdown.h2.border": "gray70",
        "markdown.h3": "bold gray46",
        "markdown.h4": "bold gray54",
    }
)
THINKING_STYLE = "italic dim"
THINKING_PREFIX = Text.from_markup("[not italic]◈[/not italic] Thinking...\n", style=THINKING_STYLE)
TOOL_NAME_STYLE = "bold"
DIFF_REMOVE_LINE_STYLE = "#333333 on #ffa8b4"
DIFF_ADDED_LINE_STYLE = "#333333 on #69db7c"


class REPLDisplay(DisplayABC):
    def __init__(self):
        self.console: Console = Console(
            theme=Theme(
                styles={
                    "diff.remove": DIFF_REMOVE_LINE_STYLE,
                    "diff.add": DIFF_ADDED_LINE_STYLE,
                }
            )
        )
        self.assistant_mdstream: MarkdownStream | None = None
        self.accumulated_assistant_text = ""
        self.stage: Literal["waiting", "thinking", "assistant", "tool_call", "tool_result"] = "waiting"
        self.is_thinking_in_bold = False

    @override
    async def consume_event(self, event: events.Event) -> None:
        match event:
            case events.TaskStartEvent():
                self.console.print()
            case events.TaskFinishEvent():
                pass
            case events.ThinkingDeltaEvent() as e:
                self.display_thinking(e)
                self.stage = "thinking"
            case events.ThinkingEvent() as e:
                self.console.print("\n")
            case events.AssistantMessageDeltaEvent() as e:
                self.accumulated_assistant_text += e.content
                if self.assistant_mdstream is None:
                    self.assistant_mdstream = MarkdownStream(mdargs={"code_theme": CODE_THEME}, theme=MARKDOWN_THEME)
                    self.stage = "assistant"
                self.assistant_mdstream.update(self.accumulated_assistant_text.strip())
            case events.AssistantMessageEvent() as e:
                if self.assistant_mdstream is not None:
                    self.assistant_mdstream.update(e.content.strip(), final=True)
                self.accumulated_assistant_text = ""
                self.assistant_mdstream = None
            case events.ResponseMetadataEvent() as e:
                self.display_metadata(e)
                self.console.print()
            case events.ToolCallEvent() as e:
                self.display_tool_call(e)
                self.stage = "tool_call"
            case events.ToolResultEvent() as e:
                self.display_tool_call_result(e)
                self.console.print()
                self.stage = "tool_result"
            case events.ReplayHistoryEvent() as e:
                await self.replay_history(e)
            case events.WelcomeEvent() as e:
                self.display_welcome(e)
            case events.ErrorEvent() as e:
                self.console.print(self.render_error(e.error_message))
            case _:
                self.console.print("[Event]", event.__class__.__name__, event)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def display_thinking(self, e: events.ThinkingDeltaEvent) -> None:
        """
        Handle markdown bold syntax in thinking text.
        ```
        """
        if len(e.content.strip()) == 0:
            return
        if self.stage != "thinking":
            self.console.print(THINKING_PREFIX)
        if e.content.count("**") == 2:
            left_part, middle_part, right_part = e.content.split("**", maxsplit=2)
            if self.is_thinking_in_bold:
                self.console.print(Text(left_part, style=f"bold {THINKING_STYLE}"), end="")
                self.console.print(Text(middle_part, style=THINKING_STYLE), end="")
                self.console.print(Text(right_part, style=f"bold {THINKING_STYLE}"), end="")
            else:
                self.console.print(Text(left_part, style=THINKING_STYLE), end="")
                self.console.print(Text(middle_part, style=f"bold {THINKING_STYLE}"), end="")
                self.console.print(Text(right_part, style=THINKING_STYLE), end="")
        elif e.content.count("**") == 1:
            left_part, right_part = e.content.split("**", maxsplit=1)
            if self.is_thinking_in_bold:
                self.console.print(Text(left_part, style=f"bold {THINKING_STYLE}"), end="")
                self.console.print(Text(right_part, style=THINKING_STYLE), end="")
            else:
                self.console.print(Text(left_part, style=THINKING_STYLE), end="")
                self.console.print(Text(right_part, style=f"bold {THINKING_STYLE}"), end="")
            self.is_thinking_in_bold = not self.is_thinking_in_bold
        else:
            if self.is_thinking_in_bold:
                self.console.print(Text(e.content, style=f"bold {THINKING_STYLE}"), end="")
            else:
                self.console.print(Text(e.content, style=THINKING_STYLE), end="")

    def render_error(self, error_msg: str) -> RenderableType:
        grid = Table.grid()
        table = Table.grid(padding=(0, 1))
        table.add_column(width=1, no_wrap=True)
        table.add_column(overflow="fold")
        grid.add_row(
            Text("✘ ", style="bold red"),
            Text(self.truncate_display(error_msg), style="red"),
        )
        return grid

    def render_any_tool_call(self, tool_name: str, arguments: str, markup: str = "•") -> Text:
        render_result: Text = Text.assemble((markup, "bold"), " ", (tool_name, TOOL_NAME_STYLE), " ")
        if not arguments:
            return render_result
        try:
            json_dict = json.loads(arguments)
            if len(json_dict) == 0:
                return render_result
            if len(json_dict) == 1:
                return render_result.append(Text(str(next(iter(json_dict.values()))), "green"))
            return render_result.append(Text(", ".join([f"{k}: {v}" for k, v in json_dict.items()]), "green"))
        except json.JSONDecodeError:
            return render_result.append(Text(arguments))

    def render_read_tool_call(self, arguments: str) -> RenderableType:
        grid = Table.grid()
        table = Table.grid(padding=(0, 1))
        table.add_column(width=1, no_wrap=True)
        table.add_column(overflow="fold")
        render_result: Text = Text.assemble(("Read", TOOL_NAME_STYLE), " ")
        try:
            json_dict = json.loads(arguments)
            file_path = json_dict.get("file_path")
            limit = json_dict.get("limit", None)
            offset = json_dict.get("offset", None)
            render_result = render_result.append(Text(file_path, "green"))
            if limit is not None and offset is not None:
                render_result = (
                    render_result.append_text(Text(" "))
                    .append_text(Text(str(offset), "bold green"))
                    .append_text(Text(":", "green"))
                    .append_text(Text(str(offset + limit - 1), "bold green"))
                )
            elif limit is not None:
                render_result = (
                    render_result.append_text(Text(" "))
                    .append_text(Text("1", "bold green"))
                    .append_text(Text(":", "green"))
                    .append_text(Text(str(limit), "bold green"))
                )
            elif offset is not None:
                render_result = (
                    render_result.append_text(Text(" "))
                    .append_text(Text(str(offset), "bold green"))
                    .append_text(Text(":", "green"))
                    .append_text(Text("-", "bold green"))
                )
        except json.JSONDecodeError:
            render_result = render_result.append_text(Text(arguments))
        grid.add_row(Text("← ", "bold"), render_result)
        return grid

    def render_edit_tool_call(self, arguments: str) -> Text:
        render_result: Text = Text.assemble(("→ ", "bold"))
        try:
            json_dict = json.loads(arguments)
            file_path = json_dict.get("file_path")
            old_string = json_dict.get("old_string", "")
            render_result = (
                render_result.append_text(Text("Create" if old_string == "" else "Edit", TOOL_NAME_STYLE))
                .append_text(Text(" "))
                .append_text(Text(file_path, "green"))
            )
        except json.JSONDecodeError:
            render_result = (
                render_result.append_text(Text("Edit", TOOL_NAME_STYLE))
                .append_text(Text(" "))
                .append_text(Text(arguments))
            )
        return render_result

    def render_multi_edit_tool_call(self, arguments: str) -> Text:
        render_result: Text = Text.assemble(("→ ", "bold"), ("MultiEdit", TOOL_NAME_STYLE), " ")
        try:
            json_dict = json.loads(arguments)
            file_path = json_dict.get("file_path")
            edits = json_dict.get("edits", [])
            render_result = (
                render_result.append_text(Text(file_path, "green"))
                .append_text(Text(" - "))
                .append_text(Text(f"{len(edits)}", "bold green"))
                .append_text(Text(" updates", "green"))
            )
        except json.JSONDecodeError:
            render_result = render_result.append_text(Text(arguments))
        return render_result

    def display_tool_call(self, e: events.ToolCallEvent) -> None:
        match e.tool_name:
            case tools.READ_TOOL_NAME:
                self.console.print(self.render_read_tool_call(e.arguments))
            case tools.EDIT_TOOL_NAME:
                self.console.print(self.render_edit_tool_call(e.arguments))
            case tools.MULTI_EDIT_TOOL_NAME:
                self.console.print(self.render_multi_edit_tool_call(e.arguments))
            case tools.BASH_TOOL_NAME:
                self.console.print(self.render_any_tool_call(e.tool_name, e.arguments, ">"))
            case tools.TODO_WRITE_TOOL_NAME:
                self.console.print(self.render_any_tool_call("Update Todos", "", "☰"))
            case _:
                self.console.print(self.render_any_tool_call(e.tool_name, e.arguments))

    def truncate_display(self, text: str) -> str:
        lines = text.split("\n")
        if len(lines) > 20:
            return "\n".join(lines[:20]) + "\n... (more " + str(len(lines) - 20) + " lines are truncated)"
        return text

    def render_edit_diff(self, e: events.ToolResultEvent) -> RenderableType:
        diff_text = e.ui_extra or ""
        if diff_text == "":
            return Text("")

        lines = diff_text.split("\n")

        grid = Table.grid()
        table = Table.grid(padding=(0, 1))
        table.add_column(width=4, no_wrap=True)
        table.add_column(overflow="fold")

        # Track line numbers based on hunk headers
        new_ln: int | None = None

        for line in lines:
            # Parse hunk headers to reset counters: @@ -l,s +l,s @@
            if line.startswith("@@"):
                try:
                    # Example: @@ -12,3 +12,4 @@ optional
                    header = line
                    parts = header.split()
                    plus = parts[2]  # like '+12,4'
                    # strip leading +/- and split by comma
                    new_start = int(plus[1:].split(",")[0])
                    new_ln = new_start
                except Exception:
                    new_ln = None
                grid.add_row("   … ", "")
                continue

            # Skip file header lines entirely
            if line.startswith("--- ") or line.startswith("+++ "):
                continue

            # Only handle unified diff hunk lines; ignore other metadata like
            # "diff --git" or "index ..." which would otherwise skew counters.
            if not line or line[:1] not in {" ", "+", "-"}:
                continue

            # Hide completely blank diff lines (no content beyond the marker)
            if len(line) == 1:
                continue

            # Compute line number prefix and advance counters
            prefix = "     "
            kind = line[0]
            if kind == "-":
                pass
            elif kind == "+":
                if new_ln is not None:
                    prefix = f"{new_ln:>4} "
                    new_ln += 1
            else:  # context line ' '
                if new_ln is not None:
                    prefix = f"{new_ln:>4} "
                    new_ln += 1

            # Style only true diff content lines
            if line.startswith("-"):
                line_style = "diff.remove"
            elif line.startswith("+"):
                line_style = "diff.add"
            else:
                line_style = ""
            text = Text(line)
            text.stylize(line_style)
            grid.add_row(prefix, text)

        return grid

    def render_todo(self, tr: events.ToolResultEvent) -> RenderableType:
        if tr.ui_extra is None:
            return self.render_error("(no content)")
        try:
            ui_extra = model.TodoUIExtra.model_validate_json(tr.ui_extra)

            grid = Table.grid()
            table = Table.grid(padding=(0, 1))
            table.add_column(width=1, no_wrap=True)
            table.add_column(overflow="fold")

            for todo in ui_extra.todos:
                is_new_completed = todo.content in ui_extra.new_completed
                match todo.status:
                    case "pending":
                        mark = "▢"
                        mark_style = "dim"
                        text_style = "dim"
                    case "in_progress":
                        mark = "◉"
                        mark_style = "blue"
                        text_style = "bold blue"
                    case "completed":
                        mark = "✔"
                        mark_style = "green" if is_new_completed else "dim"
                        text_style = "green strike bold" if is_new_completed else "dim strike"
                text = Text(todo.content)
                text.stylize(text_style)
                grid.add_row(
                    Text(f"{mark} ", style=f"bold {mark_style}"),
                    text,
                )
            return grid

        except json.JSONDecodeError as e:
            return self.render_error(str(e))

        return ""

    def display_tool_call_result(self, e: events.ToolResultEvent) -> None:
        if e.status == "error":
            self.console.print(self.render_error(e.result))
            return

        match e.tool_name:
            case tools.READ_TOOL_NAME:
                pass
            case tools.EDIT_TOOL_NAME | tools.MULTI_EDIT_TOOL_NAME:
                self.console.print(
                    Padding.indent(
                        self.render_edit_diff(e),
                        level=2,
                    )
                )
            case tools.TODO_WRITE_TOOL_NAME:
                self.console.print(self.render_todo(e))
            case _:
                self.console.print(
                    Padding.indent(
                        Text(
                            self.truncate_display(e.result),
                            style="grey50",
                        ),
                        level=2,
                    )
                )

    def display_metadata(self, e: events.ResponseMetadataEvent) -> None:
        metadata = e.metadata
        rule_text = f"[bold]{metadata.model_name}[/bold]"
        if metadata.provider is not None:
            rule_text += f" · [bold]{metadata.provider.lower()}[/bold]"
        if metadata.usage is not None:
            cached_token_str = (
                f", ([b]{format_number(metadata.usage.cached_tokens)}[/b] cached)"
                if metadata.usage.cached_tokens > 0
                else ""
            )
            reasoning_token_str = (
                f", ([b]{format_number(metadata.usage.reasoning_tokens)}[/b] reasoning)"
                if metadata.usage.reasoning_tokens > 0
                else ""
            )
            rule_text += f" · token: [b]{format_number(metadata.usage.input_tokens)}[/b] input{cached_token_str}, [b]{format_number(metadata.usage.output_tokens)}[/b] output{reasoning_token_str}"
        self.console.print(
            Rule(
                Text.from_markup(rule_text, style="bright_black", overflow="fold"),
                style="bright_black",
                align="right",
                characters="-",
            )
        )

    def display_welcome(self, e: events.WelcomeEvent) -> None:
        model_info = Text.assemble(
            (str(e.llm_config.model), "bold"), (" @ ", "dim"), (e.llm_config.provider_name, "dim")
        )
        if e.llm_config.reasoning is not None and e.llm_config.reasoning.effort:
            model_info.append_text(
                Text.assemble(("\n• reasoning-effort: ", "dim"), (e.llm_config.reasoning.effort, "bold"))
            )
        if e.llm_config.thinking is not None and e.llm_config.thinking.budget_tokens:
            model_info.append_text(
                Text.assemble(("\n• thinking-budget: ", "dim"), (str(e.llm_config.thinking.budget_tokens), "bold"))
            )
        if e.llm_config.verbosity:
            model_info.append_text(Text.assemble(("\n• verbosity: ", "dim"), (str(e.llm_config.verbosity), "bold")))
        if pr := e.llm_config.provider_routing:
            if pr.sort:
                model_info.append_text(Text.assemble(("\n• provider-sort: ", "dim"), (str(pr.sort), "bold")))
            if pr.order:
                model_info.append_text(Text.assemble(("\n• provider-order: ", "dim"), (">".join(pr.order), "bold")))

        self.console.print(
            Panel.fit(
                model_info,
                border_style="grey70",
            )
        )

    async def replay_history(self, history_events: events.ReplayHistoryEvent) -> None:
        for event in history_events.events:
            match event:
                case events.AssistantMessageEvent() as e:
                    MarkdownStream(mdargs={"code_theme": CODE_THEME}, theme=MARKDOWN_THEME).update(
                        e.content.strip(), final=True
                    )
                case events.ThinkingEvent() as e:
                    self.console.print(THINKING_PREFIX)
                    MarkdownStream(
                        mdargs={"code_theme": CODE_THEME, "style": THINKING_STYLE}, theme=MARKDOWN_THEME
                    ).update(e.content.strip(), final=True)
                case events.UserMessageEvent() as e:
                    lines = e.content.split("\n")
                    grid = Table.grid()
                    table = Table.grid(padding=(0, 1))
                    table.add_column(width=1, no_wrap=True)
                    table.add_column(overflow="fold")
                    for line in lines:
                        grid.add_row(
                            Text("┃ ", style="bright_black"),
                            Text(line, style="bright_black"),
                        )
                    self.console.print(grid)
                    self.console.print()
                case events.ToolCallEvent() as e:
                    await self.consume_event(e)
                case events.ToolResultEvent() as e:
                    await self.consume_event(e)
                case events.ResponseMetadataEvent() as e:
                    self.display_metadata(e)
                    self.console.print()
        self.console.print(
            Rule(
                title=Text(
                    "LOADED ◷ {}".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(history_events.updated_at))),
                    style="bold green",
                ),
                characters="=",
                style="green",
            )
        )
        self.console.print()
