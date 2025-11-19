from rich.text import Text

from codex_mini.ui.base.theme import ThemeKey


def thinking_prefix() -> Text:
    return Text.from_markup("[not italic]⸫[/not italic] Thinking …", style=ThemeKey.THINKING)
