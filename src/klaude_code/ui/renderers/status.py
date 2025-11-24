from rich._spinners import SPINNERS
from rich.text import Text

from klaude_code.ui.base.theme import ThemeKey

SPINNERS.update(
    {
        "claude": {
            "interval": 100,
            "frames": ["✶", "✻", "✽", "✻", "✶", "✳", "✢", "·", "✢", "✳"],
        },
        "copilot": {
            "interval": 100,
            "frames": ["∙", "∙", "◉", "◉", "●", "◉", "◉", "◎", "◎"],
        },
    }
)


def spinner_name() -> str:
    return "bouncingBall"


def render_status_text(main_text: str, main_style: ThemeKey) -> Text:
    """Create status text with main text and (esc to interrupt) suffix."""
    result = Text()
    result.append(main_text, style=main_style)
    result.append(" (esc to interrupt)", style=ThemeKey.STATUS_HINT)
    return result
