from klaude_code.ui.modes.repl.input_prompt_toolkit import REPLStatusSnapshot


def build_repl_status_snapshot(update_message: str | None) -> REPLStatusSnapshot:
    """Build a status snapshot for the REPL bottom toolbar."""
    return REPLStatusSnapshot(update_message=update_message)
