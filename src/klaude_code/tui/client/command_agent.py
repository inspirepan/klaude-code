"""Adapter that lets slash commands run against an attached (remote) session.

Commands receive an ``Agent``-shaped object (see tui/command/command_abc.py).
When the TUI is a server client there is no in-process agent; the server and
the TUI share one machine, so a read-only disk load of the session satisfies
the read paths (/copy, /export-session, /fork-session). ``profile`` is None —
commands must already handle profile-less agents.
"""

from __future__ import annotations

from pathlib import Path

from klaude_code.llm import LLMClientABC
from klaude_code.session.session import Session


class ClientCommandAgent:
    """Command-facing agent backed by the on-disk session snapshot."""

    def __init__(self, session_id: str, work_dir: Path) -> None:
        self.session: Session = Session.load(session_id, work_dir=work_dir)

    @property
    def profile(self) -> None:
        return None

    def get_llm_client(self) -> LLMClientABC:
        raise RuntimeError("LLM clients live on the server; this command is not supported while attached")
