from rich.console import Console

from .colors import ColorStyle, get_theme


class ConsoleProxy:
    def __init__(self):
        self.console = Console(theme=get_theme('dark_ansi'), style=ColorStyle.MAIN)
        self.silent = False

    def set_theme(self, theme_name: str):
        self.console = Console(theme=get_theme(theme_name), style=ColorStyle.MAIN)

    def print(self, *args, **kwargs):
        if not self.silent:
            self.console.print(*args, **kwargs)

    def set_silent(self, silent: bool):
        self.silent = silent


console = ConsoleProxy()
