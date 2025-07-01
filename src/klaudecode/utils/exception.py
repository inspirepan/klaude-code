def format_exception_brief(e: Exception) -> str:
    """
    Brief exception formatting for logging

    Args:
        e: Exception instance

    Returns:
        Brief exception description
    """
    exception_type = type(e).__name__
    exception_msg = str(e).strip() if str(e).strip() else 'No message'

    return f'[{exception_type}] {exception_msg}'
