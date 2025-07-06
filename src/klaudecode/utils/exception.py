def format_exception(e: Exception, show_traceback: bool = False) -> str:
    """
    Brief exception formatting for logging

    Args:
        e: Exception instance

    Returns:
        Brief exception description
    """
    exception_type = type(e).__name__
    exception_msg = ' (' + str(e).strip() + ')' if str(e).strip() else ''
    if show_traceback:
        import traceback

        exception_msg += f'\n{traceback.format_exc()}'

    return f'{exception_type}{exception_msg}'
