import json
from typing import Any, cast

from rich import box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from klaude_code.const import TAB_EXPAND_WIDTH
from klaude_code.protocol.models import AskUserQuestionSummaryUIExtra
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import MARK_QUESTION, render_tool_call_tree


def render_ask_user_question_tool_call(arguments: str) -> RenderableType:
    question_count = 1
    headers: list[str] = []
    if arguments:
        try:
            payload_raw: Any = json.loads(arguments)
            if isinstance(payload_raw, dict):
                payload = cast(dict[str, Any], payload_raw)
                questions: Any = payload.get("questions")
                if isinstance(questions, list) and questions:
                    question_count = len(cast(list[Any], questions))
                    for q in cast(list[dict[str, Any]], questions):
                        header = q.get("header")
                        if isinstance(header, str):
                            headers.append(header)
        except json.JSONDecodeError:
            pass

    if question_count == 1:
        tool_name = "Agent has a question for you"
    else:
        tool_name = f"Agent has {question_count} questions for you"

    details: RenderableType | None = None
    if headers:
        details = Text(" / ".join(headers), style="dim")

    return render_tool_call_tree(mark=MARK_QUESTION, tool_name=tool_name, details=details)

def render_ask_user_question_tool_result(result: str, *, is_error: bool = False) -> RenderableType:
    """Render AskUserQuestion result without truncating the middle content."""
    style = ThemeKey.ERROR if is_error else ThemeKey.TOOL_RESULT_QUESTION
    return Text(result.expandtabs(TAB_EXPAND_WIDTH), style=style, overflow="fold")

def render_ask_user_question_summary(ui_extra: AskUserQuestionSummaryUIExtra) -> RenderableType:
    """Render AskUserQuestion structured summary with highlighted answered status."""
    if not ui_extra.items:
        return Text("(No answer provided)", style=ThemeKey.WARN)

    sections: list[RenderableType] = []
    for idx, item in enumerate(ui_extra.items):
        if idx > 0:
            sections.append(Rule(style=ThemeKey.LINES))

        grid = create_grid(overflow="fold")
        grid.add_row(
            Text("\u25cf", style=ThemeKey.TOOL_RESULT_QUESTION_PROMPT),
            Text(
                item.question.expandtabs(TAB_EXPAND_WIDTH), style=ThemeKey.TOOL_RESULT_QUESTION_PROMPT, overflow="fold"
            ),
        )
        summary_style = ThemeKey.TOOL_PARAM if item.answered else ThemeKey.WARN
        summary_lines = item.summary.split("\n")
        for line in summary_lines:
            answer_text = Text()
            answer_text.append(Text("\u2192 ", style=ThemeKey.TOOL_RESULT_TRUNCATED, overflow="fold"))
            answer_text.append(line.expandtabs(TAB_EXPAND_WIDTH), style=summary_style)
            grid.add_row(
                Text(""),
                answer_text,
            )

        sections.append(grid)

    return Panel(
        Padding(Group(*sections), (0, 0, 0, 1)),
        box=box.ROUNDED,
        border_style=ThemeKey.LINES,
        expand=False,
    )
