from rich.console import Console

from .colors import ColorStyle, get_theme


class ConsoleProxy:
    def __init__(self):
        self.console = Console(theme=get_theme('dark'), style=ColorStyle.MAIN)
        self.silent = False

    def set_theme(self, theme_name: str):
        if theme_name == 'dark':
            self.console = Console(theme=get_theme('dark'), style=ColorStyle.MAIN)
        else:
            self.console = Console(theme=get_theme('light'), style=ColorStyle.MAIN)

    def print(self, *args, **kwargs):
        if not self.silent:
            self.console.print(*args, **kwargs)

    def set_silent(self, silent: bool):
        self.silent = silent


console = ConsoleProxy()
