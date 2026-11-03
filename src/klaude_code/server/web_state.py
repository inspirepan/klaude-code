"""State for a history-only Web server, without an execution Runtime."""

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from klaude_code.app.session_index import SessionIndex


@dataclass
class ReadOnlyWebState:
    home_dir: Path
    index: SessionIndex


def get_web_state(request: Request) -> ReadOnlyWebState:
    state = getattr(request.app.state, "web_state", None)
    if isinstance(state, ReadOnlyWebState):
        return state
    raise RuntimeError("Read-only Web state is not initialized")
