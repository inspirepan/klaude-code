from rich.text import Text


def format_exception(e: Exception, show_traceback: bool = False) -> Text:
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
        exception_msg = Text.assemble(" (", Text(exception_str), ")")
    else:
        exception_msg = ""

    if show_traceback:
        import traceback

        exception_msg += Text.assemble("\n", Text(traceback.format_exc()))

    return Text.assemble(exception_type, exception_msg)
