from rich import box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from klaude_code.const import TAB_EXPAND_WIDTH
from klaude_code.protocol import tools
from klaude_code.protocol.models import AskUserQuestionSummaryUIExtra
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import (
    MARK_QUESTION,
    ToolResultStatus,
    render_tool_call_tree,
    tool_result_style,
)
from klaude_code.tui.components.tools._presentation import get_tool_call_presentation


def render_ask_user_question_tool_call(arguments: str) -> RenderableType:
    presentation = get_tool_call_presentation(tools.ASK_USER_QUESTION, arguments)
    details = Text(presentation.subject, style="dim") if presentation.subject else None
    return render_tool_call_tree(mark=MARK_QUESTION, tool_name=presentation.name, details=details)


def render_ask_user_question_tool_result(result: str, *, status: ToolResultStatus = "success") -> RenderableType:
    """Render AskUserQuestion result without truncating the middle content."""
    style = tool_result_style(status, success_style=ThemeKey.TOOL_RESULT_QUESTION)
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
            label, separator, description = line.partition(": ")
            if item.answered and separator and label:
                answer_text.append(label.expandtabs(TAB_EXPAND_WIDTH), style=ThemeKey.TOOL_PARAM_BOLD)
                answer_text.append(" \u00b7 ", style=summary_style)
                answer_text.append(description.expandtabs(TAB_EXPAND_WIDTH), style=summary_style)
            else:
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
