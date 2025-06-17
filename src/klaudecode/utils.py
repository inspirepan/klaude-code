import asyncio
import functools
from typing import Any, Callable, Type, Union, Tuple
from rich.console import Console
from .tui import render_message, format_style
from rich.status import Status

console = Console()


def retry(max_retries: int = 4, backoff_base: float = 1.0, exceptions: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception, show_status: bool = True):
    """
    Retry decorator for async functions only

    Args:
        max_retries: Maximum number of retries
        backoff_base: Base delay time for backoff
        exceptions: Exception types to retry on
        show_status: Whether to show retry status messages
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    raise
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = backoff_base * (2**attempt)
                        console.print(
                            render_message(
                                format_style(
                                    f"Retry {attempt + 1}/{max_retries}: call failed - {str(e)}, waiting {delay:.1f}s",
                                    "red",
                                ),
                                status="error",
                            )
                        )
                        with Status(
                            render_message(
                                format_style(
                                    f"Waiting {delay:.1f}s...",
                                    "red",
                                ),
                                status="error",
                            )
                        ):
                            await asyncio.sleep(delay)

                console.print(
                    render_message(
                        f"Final failure: call failed after {max_retries} retries - {last_exception}",
                        status="error",
                    ),
                )
            raise last_exception

        return async_wrapper

    return decorator


def truncate_text(text: str, max_lines: int = 15) -> str:
    lines = text.splitlines()

    if len(lines) <= max_lines + 5:
        return text
    # If content has more than max_lines, truncate and show summary
    truncated_lines = lines[:max_lines]
    remaining_lines = len(lines) - max_lines
    # Add truncation indicator
    truncated_content = "\n".join(truncated_lines)
    truncated_content += f"\n... + {remaining_lines} lines"
    return truncated_content
