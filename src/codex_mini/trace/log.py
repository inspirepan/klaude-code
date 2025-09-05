from rich.console import Console

log_console = Console()


def log(*objects: str):
    log_console.print(*objects)


def log_debug(*objects: str):
    log_console.print(*objects, style="blue")
