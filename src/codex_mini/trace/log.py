from rich.console import Console
from rich.text import Text

log_console = Console()


def log(*objects: str | tuple[str, str]):
    log_console.print(*((Text(obj[0], style=obj[1]) if isinstance(obj, tuple) else obj) for obj in objects))


def log_debug(*objects: str | tuple[str, str], style: str = "blue"):
    log_console.print(
        *((Text(obj[0], style=obj[1]) if isinstance(obj, tuple) else obj) for obj in objects), style=style
    )
