from rich.console import Console

from .colors import ColorStyle, get_theme


class ConsoleProxy:
    def __init__(self):
        self.theme_name = 'dark_ansi'
        self.console = Console(theme=get_theme(self.theme_name), style=ColorStyle.MAIN)
        self.silent = False

    def set_theme(self, theme_name: str):
        self.theme_name = theme_name
        self.console = Console(theme=get_theme(theme_name), style=ColorStyle.MAIN)

    def is_dark_theme(self) -> bool:
        return 'dark' in self.theme_name

    def print(self, *args, **kwargs):
        if not self.silent:
            self.console.print(*args, **kwargs)

    def set_silent(self, silent: bool):
        self.silent = silent


console = ConsoleProxy()
