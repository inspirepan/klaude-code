from rich.text import Text


def format_exception(e: Exception, show_traceback: bool = False) -> str:
    """
    Brief exception formatting for logging

    Args:
        e: Exception instance

    Returns:
        Brief exception description
    """
    exception_type = type(e).__name__
    exception_str = str(e).strip()

    if exception_str:
        exception_str = Text(exception_str)
        exception_msg = ' (' + exception_str + ')'
    else:
        exception_msg = ''

    if show_traceback:
        import traceback

        exception_msg += f'\n{traceback.format_exc()}'

    return f'{exception_type}{exception_msg}'
