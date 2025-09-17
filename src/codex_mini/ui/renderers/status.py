from rich._spinners import SPINNERS
from rich.text import Text

from codex_mini.ui.theme import ThemeKey

SPINNERS["claude"] = {
    "interval": 150,
    "frames": ["✶", "✻", "✽", "✻", "✶", "✳", "✢", "·", "✢", "✳"],
}


def render_status_text(main_text: str, main_style: ThemeKey) -> Text:
    """Create status text with main text and (esc to interrupt) suffix."""
    result = Text()
    result.append(main_text, style=main_style)
    result.append(" (esc to interrupt)", style=ThemeKey.STATUS_HINT)
    return result
