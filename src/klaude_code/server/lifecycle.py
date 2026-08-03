"""Server lifecycle handle shared between the uvicorn runner and API routes."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path


class ServerLifecycle:
    """Lets API routes request a graceful shutdown or reload of the server.

    The runner binds a trigger (setting ``uvicorn.Server.should_exit``); route
    handlers call ``request_stop`` / ``request_reload``. After the serve loop
    exits, the runner checks ``reload_requested`` to decide whether to re-exec.
    """

    def __init__(self, *, socket_path: Path) -> None:
        self.socket_path = socket_path
        self.started_at = time.time()
        self.reload_requested = False
        self._trigger_exit: Callable[[], None] | None = None

    def bind_exit_trigger(self, trigger: Callable[[], None]) -> None:
        self._trigger_exit = trigger

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.started_at

    def request_stop(self) -> None:
        self._exit()

    def request_reload(self) -> None:
        self.reload_requested = True
        self._exit()

    def _exit(self) -> None:
        if self._trigger_exit is None:
            raise RuntimeError("Server lifecycle exit trigger is not bound")
        self._trigger_exit()
