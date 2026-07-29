from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.tui.components.rich.markdown import NoInsetMarkdown
from klaude_code.tui.components.rich.theme import ThemeKey

SIDE_QUESTION_TITLE = "btw"


def render_side_question(e: events.SideQuestionEvent, *, code_theme: str, width: int | None = None) -> RenderableType:
    """Render a `/btw` question and its answer as one bordered panel.

    The panel is the whole record of the exchange: the question is not echoed as
    a user turn, and history replay only has this event to work from.
    """
    body: list[RenderableType] = [
        Text(e.question.strip(), style=ThemeKey.SIDE_QUESTION_QUESTION, overflow="fold"),
        Text(),
        NoInsetMarkdown(e.answer.strip(), code_theme=code_theme, style=ThemeKey.SIDE_QUESTION_ANSWER),
    ]
    return Panel(
        Group(*body),
        title=Text(SIDE_QUESTION_TITLE, style=ThemeKey.SIDE_QUESTION_LABEL),
        title_align="left",
        subtitle=_render_cache_footer(e.cache_hit_rate),
        subtitle_align="right",
        box=box.ROUNDED,
        border_style=ThemeKey.LINES,
        width=width,
    )


def _render_cache_footer(cache_hit_rate: float | None) -> Text | None:
    """How much of this side question's prompt was served from the parent's cache."""
    if cache_hit_rate is None:
        return None
    return Text(f"cache hit {cache_hit_rate:.0%}", style=ThemeKey.METADATA_DIM)
