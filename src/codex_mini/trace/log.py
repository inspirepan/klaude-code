from rich.console import Console

log_console = Console()


def log(*objects: str):
    log_console.print(*objects)
