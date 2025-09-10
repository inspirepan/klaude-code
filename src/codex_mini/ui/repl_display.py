import json
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, override

from rich._spinners import SPINNERS
from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.status import Status
from rich.style import Style, StyleType
from rich.table import Table
from rich.text import Text

from codex_mini.protocol import events, model, tools
from codex_mini.protocol.commands import CommandName
from codex_mini.ui.debouncer import Debouncer
from codex_mini.ui.display_abc import DisplayABC
from codex_mini.ui.mdstream import MarkdownStream, NoInsetMarkdown
from codex_mini.ui.quote import Quote
from codex_mini.ui.theme import ThemeKey, get_theme
from codex_mini.ui.utils import format_number

THINKING_PREFIX = Text.from_markup("[not italic]◈[/not italic] Thinking...\n", style=ThemeKey.THINKING)

SPINNERS["claude"] = {
    "interval": 100,
    "frames": ["✶", "✻", "✽", "✻", "✶", "✳", "✢", "·", "✢", "✳"],
}


@dataclass
class SessionStatus:
    is_subagent: bool = False
    color: Style | None = None


class REPLDisplay(DisplayABC):
    def __init__(self, theme: str | None = None):
        self.themes = get_theme(theme)
        self.console: Console = Console(theme=self.themes.app_theme)
        self.console.push_theme(self.themes.markdown_theme)
        self.stage: Literal["waiting", "thinking", "assistant", "tool_call", "tool_result"] = "waiting"
        self.is_thinking_in_bold = False

        self.assistant_mdstream: MarkdownStream | None = None
        self.accumulated_assistant_text = ""  # Not support parallel assistant delta yet
        self.assistant_debouncer = Debouncer(interval=0.05, callback=self._flush_assistant_buffer)

        self.accumulated_thinking_text = ""  # Not support parallel thinking delta yet
        self.thinking_debouncer = Debouncer(interval=0.05, callback=self._flush_thinking_buffer)

        self.developer_message_buffer: list[events.DeveloperMessageEvent] = []

        self.session_map: dict[str, SessionStatus] = {}
        self.current_session_status: SessionStatus | None = None
        self.subagent_color_index = 0

        self.spinner: Status = self.console.status(
            Text("Thinking …", style=ThemeKey.SPINNER_STATUS),
            spinner="claude",
            spinner_style=ThemeKey.SPINNER_STATUS,
        )

    @override
    async def consume_event(self, event: events.Event) -> None:
        match event:
            case events.ReplayHistoryEvent() as e:
                await self.replay_history(e)
                self.spinner.stop()
            case events.WelcomeEvent() as e:
                self.display_welcome(e)
            case events.UserMessageEvent() as e:
                self.display_user_input(e)
            case events.TaskStartEvent() as e:
                self.spinner.start()
                self.session_map[e.session_id] = SessionStatus(
                    is_subagent=e.is_sub_agent, color=self.pick_sub_agent_color() if e.is_sub_agent else None
                )
            case events.DeveloperMessageEvent() as e:
                if self.need_display_developer_message(e):
                    # If has anything to display, send it to buffer
                    self.developer_message_buffer.append(e)
                # If it's command output, flush it immediately
                if e.item.command_output:
                    self._flush_developer_buffer()
            case events.TurnStartEvent() as e:
                self._flush_developer_buffer()
            case events.ThinkingDeltaEvent() as e:
                if self.is_sub_agent_session(e.session_id):
                    return
                self.spinner.stop()
                if len(e.content.strip()) == 0 and self.stage != "thinking":
                    # Filter leading empty delta events
                    return
                self.accumulated_thinking_text += e.content
                self.thinking_debouncer.schedule()
            case events.ThinkingEvent() as e:
                if self.is_sub_agent_session(e.session_id):
                    return
                self.thinking_debouncer.cancel()
                await self._flush_thinking_buffer()
                self.print("\n")
                self.spinner.start()
            case events.AssistantMessageDeltaEvent() as e:
                if self.is_sub_agent_session(e.session_id):
                    return
                if len(e.content.strip()) == 0 and self.stage != "assistant":
                    # Filter leading empty delta events
                    return
                self.spinner.stop()
                self.accumulated_assistant_text += e.content
                if self.assistant_mdstream is None:
                    self.assistant_mdstream = MarkdownStream(
                        mdargs={"code_theme": self.themes.code_theme}, theme=self.themes.markdown_theme
                    )
                    self.stage = "assistant"
                self.assistant_debouncer.schedule()
            case events.AssistantMessageEvent() as e:
                if self.is_sub_agent_session(e.session_id):
                    return
                if self.assistant_mdstream is not None:
                    self.assistant_debouncer.cancel()
                    self.assistant_mdstream.update(e.content.strip(), final=True)
                self.accumulated_assistant_text = ""
                self.assistant_mdstream = None
                if e.annotations:
                    self.print(self.render_annotations(e.annotations))
                self.spinner.start()
            case events.TurnToolCallStartEvent() as e:
                pass
            case events.ToolCallEvent() as e:
                self.spinner.stop()
                with self.session_print_context(e.session_id):
                    self.display_tool_call(e)
                self.stage = "tool_call"
            case events.ToolResultEvent() as e:
                self.spinner.stop()
                with self.session_print_context(e.session_id):
                    self.display_tool_call_result(e)
                    self.print()
                self.stage = "tool_result"
                self.spinner.start()
            case events.ResponseMetadataEvent() as e:
                with self.session_print_context(e.session_id):
                    self.display_metadata(e)
                    self.print()
            case events.TodoChangeEvent() as e:
                active_form_status_text = ""
                for todo in e.todos:
                    if todo.status == "in_progress":
                        if len(todo.activeForm) > 0:
                            active_form_status_text = todo.activeForm
                            break
                        elif len(todo.content) > 0:
                            active_form_status_text = todo.content
                            break
                if len(active_form_status_text) > 0:
                    self.spinner.update(Text(active_form_status_text + " …", style=ThemeKey.SPINNER_STATUS_BOLD))
                else:
                    self.spinner.update(Text("Thinking …", style=ThemeKey.SPINNER_STATUS))
            case events.TurnEndEvent():
                pass
            case events.TaskFinishEvent():
                self.spinner.stop()
            case events.InterruptEvent() as e:
                self.display_interrupt(e)
                self.spinner.stop()
            case events.ErrorEvent() as e:
                self.print(self.render_error(e.error_message))
                self.spinner.stop()
            case events.EndEvent():
                self.spinner.stop()
            # case _:
            #     self.print("[Event]", event.__class__.__name__, event)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        await self.assistant_debouncer.flush()
        await self.thinking_debouncer.flush()
        self.assistant_debouncer.cancel()
        self.thinking_debouncer.cancel()
        pass

    def is_sub_agent_session(self, session_id: str) -> bool:
        return session_id in self.session_map and self.session_map[session_id].is_subagent

    def pick_sub_agent_color(self, switch: bool = False) -> Style:
        if switch:
            self.subagent_color_index = (self.subagent_color_index + 1) % len(self.themes.sub_agent_colors)
        return self.console.get_style(self.themes.sub_agent_colors[self.subagent_color_index])

    @contextmanager
    def session_print_context(self, session_id: str):
        """Context manager for subagent QuoteStyle"""
        old = self.current_session_status
        if session_id in self.session_map:
            # For sub-agent
            self.current_session_status = self.session_map[session_id]
        try:
            yield
        finally:
            self.current_session_status = old

    def print(self, *objects: Any, style: StyleType | None = None, end: str = "\n"):
        if (
            self.current_session_status
            and self.current_session_status.is_subagent
            and self.current_session_status.color
        ):
            # If it's sub-agent
            if objects:
                self.console.print(Quote(*objects, style=self.current_session_status.color))
            else:
                self.console.print(Quote("", style=self.current_session_status.color))
        else:
            self.console.print(*objects, style=style, end=end)

    async def _flush_assistant_buffer(self) -> None:
        """Flush assistant buffer"""
        if self.assistant_mdstream is not None:
            self.assistant_mdstream.update(self.accumulated_assistant_text.strip())

    async def _flush_thinking_buffer(self) -> None:
        """Flush thinking buffer"""
        content = self.accumulated_thinking_text.replace("\r", "").replace("\n\n", "\n")
        if len(content.strip()) == 0:
            self.accumulated_thinking_text = ""
            return
        self._render_thinking_content(content)
        self.accumulated_thinking_text = ""

    def _render_thinking_content(self, content: str) -> None:
        """
        Handle markdown bold syntax in thinking text.
        """
        if self.stage != "thinking":
            self.print(THINKING_PREFIX)
            self.stage = "thinking"
        if content.count("**") == 2:
            left_part, middle_part, right_part = content.split("**", maxsplit=2)
            if self.is_thinking_in_bold:
                self.print(Text(left_part, style=ThemeKey.THINKING_BOLD), end="")
                self.print(Text(middle_part, style=ThemeKey.THINKING), end="")
                self.print(Text(right_part, style=ThemeKey.THINKING_BOLD), end="")
            else:
                self.print(Text(left_part, style=ThemeKey.THINKING), end="")
                self.print(Text(middle_part, style=ThemeKey.THINKING_BOLD), end="")
                self.print(Text(right_part, style=ThemeKey.THINKING), end="")
        elif content.count("**") == 1:
            left_part, right_part = content.split("**", maxsplit=1)
            if self.is_thinking_in_bold:
                self.print(Text(left_part, style=ThemeKey.THINKING_BOLD), end="")
                self.print(Text(right_part, style=ThemeKey.THINKING), end="")
            else:
                self.print(Text(left_part, style=ThemeKey.THINKING), end="")
                self.print(Text(right_part, style=ThemeKey.THINKING_BOLD), end="")
            self.is_thinking_in_bold = not self.is_thinking_in_bold
        else:
            if self.is_thinking_in_bold:
                self.print(Text(content, style=ThemeKey.THINKING_BOLD), end="")
            else:
                self.print(Text(content, style=ThemeKey.THINKING), end="")

    def _create_grid(self) -> Table:
        """Create a standard two-column grid table to align the text in the second column."""
        grid = Table.grid(padding=(0, 1))
        grid.add_column(no_wrap=True)
        grid.add_column(overflow="fold")
        return grid

    def render_error(self, error_msg: str) -> RenderableType:
        grid = self._create_grid()
        grid.add_row(
            Text("✘", style=ThemeKey.ERROR_BOLD),
            Text(self.truncate_display(error_msg), style=ThemeKey.ERROR),
        )
        return grid

    def render_path(self, path: str, style: StyleType, is_directory: bool = False) -> Text:
        """Render path with home shortcuts and relative path."""
        if path.startswith(str(Path().cwd())):
            path = path.replace(str(Path().cwd()), "").lstrip("/")
        elif path.startswith(str(Path().home())):
            path = path.replace(str(Path().home()), "~")
        elif not path.startswith("/") and not path.startswith("."):
            path = "./" + path
        if is_directory:
            path = path.rstrip("/") + "/"
        return Text(path, style=style)

    def render_any_tool_call(self, tool_name: str, arguments: str, markup: str = "•") -> Text:
        render_result: Text = Text.assemble((markup, ThemeKey.TOOL_MARK), " ", (tool_name, ThemeKey.TOOL_NAME), " ")
        if not arguments:
            return render_result
        try:
            json_dict = json.loads(arguments)
            if len(json_dict) == 0:
                return render_result
            if len(json_dict) == 1:
                return render_result.append_text(Text(str(next(iter(json_dict.values()))), ThemeKey.TOOL_PARAM))
            return render_result.append_text(
                Text(", ".join([f"{k}: {v}" for k, v in json_dict.items()]), ThemeKey.TOOL_PARAM)
            )
        except json.JSONDecodeError:
            return render_result.append_text(Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS))

    def render_read_tool_call(self, arguments: str) -> RenderableType:
        grid = self._create_grid()
        render_result: Text = Text.assemble(("Read", ThemeKey.TOOL_NAME), " ")
        try:
            json_dict = json.loads(arguments)
            file_path = json_dict.get("file_path")
            limit = json_dict.get("limit", None)
            offset = json_dict.get("offset", None)
            render_result = render_result.append(self.render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
            if limit is not None and offset is not None:
                render_result = (
                    render_result.append_text(Text(" "))
                    .append_text(Text(str(offset), ThemeKey.TOOL_PARAM_BOLD))
                    .append_text(Text(":", ThemeKey.TOOL_PARAM))
                    .append_text(Text(str(offset + limit - 1), ThemeKey.TOOL_PARAM_BOLD))
                )
            elif limit is not None:
                render_result = (
                    render_result.append_text(Text(" "))
                    .append_text(Text("1", ThemeKey.TOOL_PARAM_BOLD))
                    .append_text(Text(":", ThemeKey.TOOL_PARAM))
                    .append_text(Text(str(limit), ThemeKey.TOOL_PARAM_BOLD))
                )
            elif offset is not None:
                render_result = (
                    render_result.append_text(Text(" "))
                    .append_text(Text(str(offset), ThemeKey.TOOL_PARAM_BOLD))
                    .append_text(Text(":", ThemeKey.TOOL_PARAM))
                    .append_text(Text("-", ThemeKey.TOOL_PARAM_BOLD))
                )
        except json.JSONDecodeError:
            render_result = render_result.append_text(Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS))
        grid.add_row(Text("←", ThemeKey.TOOL_MARK), render_result)
        return grid

    def render_edit_tool_call(self, arguments: str) -> Text:
        render_result: Text = Text.assemble(("→ ", ThemeKey.TOOL_MARK))
        try:
            json_dict = json.loads(arguments)
            file_path = json_dict.get("file_path")
            old_string = json_dict.get("old_string", "")
            render_result = (
                render_result.append_text(Text("Create" if old_string == "" else "Edit", ThemeKey.TOOL_NAME))
                .append_text(Text(" "))
                .append_text(self.render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
            )
        except json.JSONDecodeError:
            render_result = (
                render_result.append_text(Text("Edit", ThemeKey.TOOL_NAME))
                .append_text(Text(" "))
                .append_text(Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS))
            )
        return render_result

    def render_multi_edit_tool_call(self, arguments: str) -> Text:
        render_result: Text = Text.assemble(("→ ", ThemeKey.TOOL_MARK), ("MultiEdit", ThemeKey.TOOL_NAME), " ")
        try:
            json_dict = json.loads(arguments)
            file_path = json_dict.get("file_path")
            edits = json_dict.get("edits", [])
            render_result = (
                render_result.append_text(self.render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
                .append_text(Text(" - "))
                .append_text(Text(f"{len(edits)}", ThemeKey.TOOL_PARAM_BOLD))
                .append_text(Text(" updates", ThemeKey.TOOL_PARAM_FILE_PATH))
            )
        except json.JSONDecodeError:
            render_result = render_result.append_text(Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS))
        return render_result

    def render_plan(self, arguments: str) -> RenderableType:
        # Plan mode
        try:
            json_dict = json.loads(arguments)
            plan = json_dict.get("plan", "")
            return Group(
                Text.assemble(("¶ ", ThemeKey.TOOL_MARK), ("Plan", ThemeKey.TOOL_NAME)),
                Panel.fit(NoInsetMarkdown(plan, code_theme=self.themes.code_theme), border_style=ThemeKey.LINES),
            )

        except json.JSONDecodeError:
            return Text.assemble(
                ("¶ ", ThemeKey.TOOL_MARK),
                ("Plan", ThemeKey.TOOL_NAME),
                " ",
                Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS),
            )

    def render_task_call(self, e: events.ToolCallEvent) -> RenderableType:
        # For sub-agent
        try:
            json_dict = json.loads(e.arguments)
            description = json_dict.get("description", "")
            prompt = json_dict.get("prompt", "")

            return Group(
                Text.assemble(
                    ("↓ ", ThemeKey.TOOL_MARK),
                    ("Task", ThemeKey.TOOL_NAME),
                    " ",
                    Text(
                        f" {description} ",
                        style=Style(color=self.pick_sub_agent_color(switch=True).color, bold=True, reverse=True),
                    ),
                ),
                Quote(
                    Text(prompt + "\n", style=self.pick_sub_agent_color()),
                    style=self.pick_sub_agent_color(),
                ),
            )

        except json.JSONDecodeError:
            return Text.assemble(
                ("↓ ", ThemeKey.TOOL_MARK),
                ("Task", ThemeKey.TOOL_NAME),
                " ",
                Text(e.arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS),
            )

    def display_tool_call(self, e: events.ToolCallEvent) -> None:
        match e.tool_name:
            case tools.READ:
                self.print(self.render_read_tool_call(e.arguments))
            case tools.EDIT:
                self.print(self.render_edit_tool_call(e.arguments))
            case tools.MULTI_EDIT:
                self.print(self.render_multi_edit_tool_call(e.arguments))
            case tools.BASH:
                self.print(self.render_any_tool_call(e.tool_name, e.arguments, "$"))
            case tools.TODO_WRITE:
                self.print(self.render_any_tool_call("Update Todos", "", "☰"))
            case tools.EXIT_PLAN_MODE:
                self.print(self.render_plan(e.arguments))
            case tools.TASK:
                self.print(self.render_task_call(e))
            case _:
                self.print(self.render_any_tool_call(e.tool_name, e.arguments))

    def truncate_display(self, text: str, max_lines: int = 20, max_line_length: int = 1000) -> str:
        lines = text.split("\n")
        if len(lines) > max_lines:
            lines = lines[:max_lines] + ["... (more " + str(len(lines) - max_lines) + " lines)"]
        for i, line in enumerate(lines):
            if len(line) > max_line_length:
                lines[i] = (
                    line[:max_line_length]
                    + "... (more "
                    + str(len(line) - max_line_length)
                    + " characters in this line)"
                )
        return "\n".join(lines)

    def render_edit_diff(self, diff_text: str, show_file_name: bool = False) -> RenderableType:
        if diff_text == "":
            return Text("")

        lines = diff_text.split("\n")
        grid = self._create_grid()

        # Track line numbers based on hunk headers
        new_ln: int | None = None

        for line in lines:
            # Parse file name from diff headers
            if show_file_name and line.startswith("+++ "):
                # Extract file name from +++ b/path header
                file_name = line[4:].split("/", 1)[-1] if "/" in line[4:] else line[4:]
                file_text = self.render_path(file_name, "bold")
                grid.add_row("", "")
                grid.add_row(Text("   ±", style=ThemeKey.TOOL_MARK), file_text)
                continue

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
                grid.add_row(Text("   …", style=ThemeKey.TOOL_RESULT), "")
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
            prefix = "    "
            kind = line[0]
            if kind == "-":
                pass
            elif kind == "+":
                if new_ln is not None:
                    prefix = f"{new_ln:>4}"
                    new_ln += 1
            else:  # context line ' '
                if new_ln is not None:
                    prefix = f"{new_ln:>4}"
                    new_ln += 1

            # Style only true diff content lines
            if line.startswith("-"):
                line_style = ThemeKey.DIFF_REMOVE
            elif line.startswith("+"):
                line_style = ThemeKey.DIFF_ADD
            else:
                line_style = ThemeKey.TOOL_RESULT
            text = Text(line)
            if line_style:
                text.stylize(line_style)
            grid.add_row(Text(prefix, ThemeKey.TOOL_RESULT), text)

        return grid

    def render_todo(self, tr: events.ToolResultEvent) -> RenderableType:
        if tr.ui_extra is None:
            return self.render_error("(no content)")
        try:
            ui_extra = model.TodoUIExtra.model_validate_json(tr.ui_extra)
            grid = self._create_grid()

            for todo in ui_extra.todos:
                is_new_completed = todo.content in ui_extra.new_completed
                match todo.status:
                    case "pending":
                        mark = "▢"
                        mark_style = ThemeKey.TODO_PENDING_MARK
                        text_style = ThemeKey.TODO_PENDING
                    case "in_progress":
                        mark = "◉"
                        mark_style = ThemeKey.TODO_IN_PROGRESS_MARK
                        text_style = ThemeKey.TODO_IN_PROGRESS
                    case "completed":
                        mark = "✔"
                        mark_style = (
                            ThemeKey.TODO_NEW_COMPLETED_MARK if is_new_completed else ThemeKey.TODO_COMPLETED_MARK
                        )
                        text_style = ThemeKey.TODO_NEW_COMPLETED if is_new_completed else ThemeKey.TODO_COMPLETED
                text = Text(todo.content)
                text.stylize(text_style)

                grid.add_row(
                    Text(mark, style=mark_style),
                    text,
                )
            return grid

        except json.JSONDecodeError as e:
            return self.render_error(str(e))

    def render_task_result(self, e: events.ToolResultEvent) -> RenderableType:
        # For sub-agent
        return Quote(
            NoInsetMarkdown(e.result, code_theme=self.themes.code_theme),
            style=self.pick_sub_agent_color(),
        )

    def display_tool_call_result(self, e: events.ToolResultEvent) -> None:
        if e.status == "error" and not e.ui_extra:
            self.print(self.render_error(e.result))
            return

        match e.tool_name:
            case tools.READ:
                pass
            case tools.EDIT | tools.MULTI_EDIT:
                self.print(
                    Padding.indent(
                        self.render_edit_diff(e.ui_extra or ""),
                        level=2,
                    )
                )
            case tools.TODO_WRITE:
                self.print(self.render_todo(e))
            case tools.EXIT_PLAN_MODE:
                # Plan mode
                if e.status == "success":
                    self.print(Padding.indent(Text(" Approved ", ThemeKey.TOOL_APPROVED), level=1))
                    grid = self._create_grid()
                    grid.add_row(
                        Text("↓", style=ThemeKey.METADATA),
                        Text(e.ui_extra or "N/A", style=ThemeKey.METADATA_BOLD),
                    )
                    self.print()
                    self.print(grid)
                else:
                    self.print(Padding.indent(Text(" Rejected ", ThemeKey.TOOL_APPROVED), level=1))
            case tools.TASK:
                self.print(self.render_task_result(e))
            case _:
                # handle bash `git diff`
                if e.tool_name == tools.BASH and e.result.startswith("diff --git"):
                    self.print(self.render_edit_diff(e.result, show_file_name=True))
                    return

                if len(e.result.strip()) == 0:
                    e.result = "(no content)"
                self.print(
                    Padding.indent(
                        Text(
                            self.truncate_display(e.result),
                            style=ThemeKey.TOOL_RESULT,
                        ),
                        level=2,
                    )
                )

    def display_metadata(self, e: events.ResponseMetadataEvent) -> None:
        metadata = e.metadata
        rule_text = Text()
        rule_text.append_text(Text(metadata.model_name, style=ThemeKey.METADATA_BOLD))
        if metadata.provider is not None:
            rule_text.append_text(Text(" "))
            rule_text.append_text(Text(metadata.provider.lower(), style=ThemeKey.METADATA))
        if metadata.usage is not None:
            cached_token_str = (
                Text.assemble((", ", ThemeKey.METADATA_DIM), format_number(metadata.usage.cached_tokens), " cached")
                if metadata.usage.cached_tokens > 0
                else Text("")
            )
            reasoning_token_str = (
                Text.assemble(
                    (", ", ThemeKey.METADATA_DIM), format_number(metadata.usage.reasoning_tokens), " reasoning"
                )
                if metadata.usage.reasoning_tokens > 0
                else Text("")
            )
            rule_text.append_text(
                Text.assemble(
                    (" → ", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.input_tokens), ThemeKey.METADATA),
                    (" input"),
                    cached_token_str,
                    (", ", ThemeKey.METADATA_DIM),
                    (format_number(metadata.usage.output_tokens), ThemeKey.METADATA),
                    (" output"),
                    reasoning_token_str,
                    style=ThemeKey.METADATA,
                )
            )
        self.print(
            Rule(
                rule_text,
                style=ThemeKey.LINES,
                align="right",
                characters="-",
            )
        )

    def display_welcome(self, e: events.WelcomeEvent) -> None:
        model_info = Text.assemble(
            (str(e.llm_config.model), ThemeKey.WELCOME_HIGHLIGHT),
            (" @ ", ThemeKey.WELCOME_INFO),
            (e.llm_config.provider_name, ThemeKey.WELCOME_INFO),
        )
        if e.llm_config.reasoning is not None and e.llm_config.reasoning.effort:
            model_info.append_text(
                Text.assemble(
                    ("\n• reasoning-effort: ", ThemeKey.WELCOME_INFO),
                    (e.llm_config.reasoning.effort, ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
        if e.llm_config.reasoning is not None and e.llm_config.reasoning.summary:
            model_info.append_text(
                Text.assemble(
                    ("\n• reasoning-summary: ", ThemeKey.WELCOME_INFO),
                    (e.llm_config.reasoning.summary, ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
        if e.llm_config.thinking is not None and e.llm_config.thinking.budget_tokens:
            model_info.append_text(
                Text.assemble(
                    ("\n• thinking-budget: ", ThemeKey.WELCOME_INFO),
                    (str(e.llm_config.thinking.budget_tokens), ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
        if e.llm_config.verbosity:
            model_info.append_text(
                Text.assemble(
                    ("\n• verbosity: ", ThemeKey.WELCOME_INFO),
                    (str(e.llm_config.verbosity), ThemeKey.WELCOME_HIGHLIGHT),
                )
            )
        if pr := e.llm_config.provider_routing:
            if pr.sort:
                model_info.append_text(
                    Text.assemble(
                        ("\n• provider-sort: ", ThemeKey.WELCOME_INFO), (str(pr.sort), ThemeKey.WELCOME_HIGHLIGHT)
                    )
                )
            if pr.only:
                model_info.append_text(
                    Text.assemble(
                        ("\n• provider-only: ", ThemeKey.WELCOME_INFO), (">".join(pr.only), ThemeKey.WELCOME_HIGHLIGHT)
                    )
                )
            if pr.order:
                model_info.append_text(
                    Text.assemble(
                        ("\n• provider-order: ", ThemeKey.WELCOME_INFO),
                        (">".join(pr.order), ThemeKey.WELCOME_HIGHLIGHT),
                    )
                )
        if pl := e.llm_config.plugins:
            model_info.append_text(Text.assemble(("\n•", ThemeKey.WELCOME_INFO)))
            for p in pl:
                model_info.append_text(Text.assemble(" ", (p.id, ThemeKey.WELCOME_HIGHLIGHT)))

        self.print(
            Panel.fit(
                model_info,
                border_style=ThemeKey.LINES,
            )
        )
        self.print()

    def render_at_pattern(
        self,
        text: str,
        at_style: str = ThemeKey.USER_INPUT_AT_PATTERN,
        other_style: str = ThemeKey.USER_INPUT,
    ) -> Text:
        if "@" in text:
            parts = re.split(r"(\s+)", text)
            result = Text("")
            for s in parts:
                if s.startswith("@"):
                    result.append_text(Text(s, at_style))
                else:
                    result.append_text(Text(s, other_style))
            return result
        return Text(text, style=other_style)

    def display_interrupt(self, e: events.InterruptEvent) -> None:
        self.print("\n INTERRUPTED \n", style=ThemeKey.INTERRUPT)

    def is_valid_slash_command(self, command: str) -> bool:
        try:
            CommandName(command)
            return True
        except ValueError:
            return False

    def display_user_input(self, e: events.UserMessageEvent) -> None:
        lines = e.content.split("\n")
        for i, line in enumerate(lines):
            line_text = self.render_at_pattern(line, ThemeKey.USER_INPUT_AT_PATTERN)  # 默认处理

            if i == 0 and line.startswith("/"):
                splits = line.split(" ", maxsplit=1)
                if self.is_valid_slash_command(splits[0][1:]):
                    if len(splits) <= 1:
                        line_text = Text(line, style=ThemeKey.USER_INPUT_SLASH_COMMAND)
                    else:
                        line_text = Text.assemble(
                            (splits[0], ThemeKey.USER_INPUT_SLASH_COMMAND),
                            " ",
                            self.render_at_pattern(splits[1], ThemeKey.USER_INPUT_AT_PATTERN),
                        )

            self.print(
                Quote(
                    line_text,
                    style=ThemeKey.USER_INPUT_DIM,
                )
            )

        self.print()

    async def replay_history(self, history_events: events.ReplayHistoryEvent) -> None:
        tool_call_dict: dict[str, events.ToolCallEvent] = {}
        for event in history_events.events:
            match event:
                case events.AssistantMessageEvent() as e:
                    if len(e.content.strip()) > 0:
                        MarkdownStream(
                            mdargs={"code_theme": self.themes.code_theme}, theme=self.themes.markdown_theme
                        ).update(e.content.strip(), final=True)
                    if e.annotations:
                        self.print(self.render_annotations(e.annotations))
                case events.ThinkingEvent() as e:
                    if len(e.content.strip()) > 0:
                        self.print(THINKING_PREFIX)
                        MarkdownStream(
                            mdargs={
                                "code_theme": self.themes.code_theme,
                                "style": self.console.get_style(ThemeKey.THINKING),
                            },
                            theme=self.themes.markdown_theme,
                        ).update(e.content.strip(), final=True)
                case events.DeveloperMessageEvent() as e:
                    self.display_developer_message(e, with_ending_line=True)
                case events.UserMessageEvent() as e:
                    self.display_user_input(e)
                case events.ToolCallEvent() as e:
                    tool_call_dict[e.tool_call_id] = e
                case events.ToolResultEvent() as e:
                    tool_call_event = tool_call_dict.get(e.tool_call_id)
                    if tool_call_event is not None:
                        self.display_tool_call(tool_call_event)
                    tool_call_dict.pop(e.tool_call_id, None)
                    # TODO: Replay Sub-Agent Events
                    self.display_tool_call_result(e)
                    self.print()
                case events.ResponseMetadataEvent() as e:
                    self.display_metadata(e)
                    self.print()
                case events.InterruptEvent() as e:
                    self.display_interrupt(e)
        if history_events.is_load:
            self.print(
                Text.assemble(
                    Text(" LOADED ", style=ThemeKey.RESUME_FLAG),
                    Text(
                        " ◷ {}".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(history_events.updated_at))),
                        style=ThemeKey.RESUME_INFO,
                    ),
                )
            )
        self.print()

    def render_annotations(self, annotations: list[model.Annotation]) -> RenderableType:
        grid = self._create_grid()
        for annotation in annotations:
            match annotation.type:
                case "url_citation":
                    if not annotation.url_citation:
                        continue
                    url = Text(
                        annotation.url_citation.title,
                    )
                    url.stylize(
                        Style(
                            color=self.console.get_style(name=ThemeKey.ANNOTATION_URL).color,
                            reverse=True,
                            bold=True,
                            underline=True,
                            link=annotation.url_citation.url,
                        )
                    )
                    grid.add_row(Text("○", style=ThemeKey.ANNOTATION_URL_HIGHLIGHT), url)
                    grid.add_row(
                        "",
                        NoInsetMarkdown(
                            self.truncate_display(annotation.url_citation.content, max_lines=30),
                            style=ThemeKey.ANNOTATION_SEARCH_CONTENT,
                        ),
                    )
                    grid.add_row("", "")
        return grid

    def _flush_developer_buffer(self) -> None:
        if len(self.developer_message_buffer) == 0:
            return

        with self.session_print_context(self.developer_message_buffer[0].session_id):
            for e in self.developer_message_buffer:
                self.display_developer_message(e)
            self.developer_message_buffer.clear()
            self.print()

    def need_display_developer_message(self, e: events.DeveloperMessageEvent) -> bool:
        return (
            bool(e.item.memory_paths)
            or bool(e.item.external_file_changes)
            or bool(e.item.todo_use)
            or bool(e.item.at_files)
            or bool(e.item.command_output)
        )

    def display_developer_message(self, e: events.DeveloperMessageEvent, with_ending_line: bool = False) -> None:
        if mp := e.item.memory_paths:
            grid = self._create_grid()
            for memory_path in mp:
                grid.add_row(
                    Text("✪", style=ThemeKey.REMINDER),
                    Text.assemble(
                        self.render_path(memory_path, ThemeKey.REMINDER_DIM),
                    ),
                )
            self.print(grid)
            if with_ending_line:
                self.print()

        if fc := e.item.external_file_changes:
            grid = self._create_grid()
            for file_path in fc:
                grid.add_row(
                    Text("⧉ ", style=ThemeKey.REMINDER),
                    Text.assemble(
                        ("Hint ", ThemeKey.REMINDER_BOLD),
                        self.render_path(file_path, ThemeKey.REMINDER_DIM),
                        (" has changed, new content has been loaded to context", ThemeKey.REMINDER_DIM),
                    ),
                )
            self.print(grid)
            if with_ending_line:
                self.print()

        if e.item.todo_use:
            self.print(
                Text.assemble(
                    Text("★ ", style=ThemeKey.REMINDER_BOLD),
                    Text("Hint ", ThemeKey.REMINDER_BOLD),
                    Text("Todo hasn't been updated recently", ThemeKey.REMINDER_DIM),
                )
            )
            if with_ending_line:
                self.print()

        if e.item.at_files:
            grid = self._create_grid()
            for at_file in e.item.at_files:
                grid.add_row(
                    Text("⧉ ", style=ThemeKey.REMINDER_BOLD),
                    Text.assemble(
                        (f"{at_file.operation} ", ThemeKey.REMINDER_BOLD),
                        self.render_path(at_file.path, ThemeKey.REMINDER_DIM),
                    ),
                )
            self.print(grid)
            if with_ending_line:
                self.print()

        if e.item.command_output:
            self.display_command_output(e)
            if with_ending_line:
                self.print()

    def display_command_output(self, e: events.DeveloperMessageEvent) -> None:
        if not e.item.command_output:
            return
        print("\033[1A\033[K", end="")  # Clear previous empty line
        match e.item.command_output.command_name:
            case CommandName.DIFF:
                if e.item.content is None or len(e.item.content) == 0:
                    self.print(
                        Padding.indent(
                            Text(
                                "(no changes)",
                                style=ThemeKey.TOOL_RESULT,
                            ),
                            level=2,
                        )
                    )
                else:
                    self.print(self.render_edit_diff(e.item.content, show_file_name=True))
            case CommandName.HELP:
                self.print(Padding.indent(Text.from_markup(e.item.content or ""), level=2))
            case CommandName.PLAN:
                # Plan mode
                self.print()
                grid = self._create_grid()
                grid.add_row(
                    Text("↓", style=ThemeKey.METADATA),
                    Text(e.item.command_output.ui_extra or "N/A", style=ThemeKey.METADATA_BOLD),
                )
                self.print(grid)
            case _:
                if e.item.content is None:
                    e.item.content = "(no content)"
                self.print(
                    Padding.indent(
                        Text(
                            self.truncate_display(e.item.content),
                            style=ThemeKey.TOOL_RESULT if not e.item.command_output.is_error else ThemeKey.ERROR,
                        ),
                        level=2,
                    )
                )
