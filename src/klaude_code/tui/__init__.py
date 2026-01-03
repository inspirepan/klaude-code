"""Terminal (TUI) frontend for klaude-code.

This package contains all terminal-specific UI code (Rich rendering,
prompt-toolkit input, and terminal integrations).

The tui layer may depend on `klaude_code.ui`, but `klaude_code.ui` must not
depend on `klaude_code.tui`.
"""
