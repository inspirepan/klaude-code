from rich.text import Text

from klaude_code.ui.rich.theme import ThemeKey


def thinking_prefix() -> Text:
    return Text.from_markup("[not italic]⸫[/not italic] Thinking …", style=ThemeKey.THINKING)
