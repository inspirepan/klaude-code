from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from klaude_code.server.session_index import SessionIndex


class SessionLiveState:
    def __init__(self, *, home_dir: Path) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self.index = SessionIndex(home=home_dir)

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def apply_meta_update(self, session_id: str, meta: dict[str, Any]) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._apply_meta_update_now, session_id, dict(meta))

    def _apply_meta_update_now(self, session_id: str, meta: dict[str, Any]) -> None:
        self.index.apply_meta(meta, fallback_session_id=session_id)
