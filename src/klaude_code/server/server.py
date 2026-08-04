from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import signal
import threading
from collections.abc import Generator
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import IO

import uvicorn
import uvicorn.server

from klaude_code.app.runtime import AppInitConfig, cleanup_app_components, initialize_app_components
from klaude_code.const import LOG_BACKUP_COUNT, LOG_MAX_BYTES
from klaude_code.log import DebugType, log_debug
from klaude_code.server.app import create_app
from klaude_code.server.display import ServerDisplay
from klaude_code.server.interaction import ServerInteractionHandler
from klaude_code.server.lifecycle import ServerLifecycle
from klaude_code.server.live_events import start_server_live_events
from klaude_code.server.paths import server_lock_path, server_log_file_path, server_run_dir, server_socket_path


class ServerAlreadyRunningError(RuntimeError):
    """Raised when another server instance is already active for this home directory."""


class _SingletonLock:
    """flock-based single-instance guard for the server process.

    The lock file lives next to the socket and is held (not removed) for the
    whole server lifetime; the OS releases the lock if the process dies.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: IO[str] | None = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self._path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            existing_pid = ""
            with contextlib.suppress(OSError):
                _ = lock_file.seek(0)
                existing_pid = lock_file.read().strip()
            lock_file.close()
            hint = f" (pid {existing_pid})" if existing_pid else ""
            raise ServerAlreadyRunningError(
                f"klaude server is already running{hint}: lock held on {self._path}"
            ) from None
        _ = lock_file.seek(0)
        lock_file.truncate()
        _ = lock_file.write(f"{os.getpid()}\n")
        lock_file.flush()
        self._file = lock_file

    def release(self) -> None:
        if self._file is None:
            return
        with contextlib.suppress(OSError):
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
        self._file = None


def _attach_server_file_logging(*, debug: bool) -> Path:
    """Mirror uvicorn logs into ~/.klaude/logs/server.log for `klaude server logs`."""

    log_path = server_log_file_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8")
    handler.setLevel(logging.DEBUG if debug else logging.INFO)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s %(message)s"))
    # "uvicorn.error" propagates to "uvicorn"; "uvicorn.access" does not.
    for logger_name in ("uvicorn", "uvicorn.access"):
        logging.getLogger(logger_name).addHandler(handler)
    return log_path


class _QuietServer(uvicorn.Server):
    """uvicorn.Server that does not re-raise captured signals on exit.

    Upstream ``capture_signals`` restores the original signal handlers and then
    calls ``signal.raise_signal()`` for every signal it captured during the
    run.  When the server was interrupted with Ctrl-C twice, this re-raise
    triggers asyncio's ``_on_sigint`` which raises ``KeyboardInterrupt`` and
    produces a noisy traceback.  This subclass keeps the graceful-shutdown
    behaviour (via ``handle_exit``) but skips the post-shutdown re-raise.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Generator[None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        original_handlers = {sig: signal.signal(sig, self.handle_exit) for sig in uvicorn.server.HANDLED_SIGNALS}
        try:
            yield
        finally:
            for sig, handler in original_handlers.items():
                _ = signal.signal(sig, handler)


async def start_server(*, debug: bool = False) -> bool:
    """Run the server on the Unix domain socket until stopped.

    Returns True when the shutdown was caused by a reload request; the caller
    is expected to re-exec the process with the original arguments.
    """

    home_dir = Path.home()

    run_dir = server_run_dir(home_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(run_dir, 0o700)

    lock = _SingletonLock(server_lock_path(home_dir))
    lock.acquire()
    try:
        socket_path = server_socket_path(home_dir)
        # The flock guarantees no live owner; drop any stale socket file.
        socket_path.unlink(missing_ok=True)

        interaction_handler = ServerInteractionHandler()
        components = await initialize_app_components(
            init_config=AppInitConfig(model=None, debug=debug, vanilla=False),
            display=ServerDisplay(),
            interaction_handler=None,
        )
        live_events = start_server_live_events(components.event_bus)

        lifecycle = ServerLifecycle(socket_path=socket_path)
        app = create_app(
            runtime=components.runtime,
            event_bus=components.event_bus,
            event_stream=live_events.stream,
            interaction_handler=interaction_handler,
            work_dir=Path.cwd(),
            home_dir=home_dir,
            lifecycle=lifecycle,
        )

        config = uvicorn.Config(
            app,
            uds=str(socket_path),
            log_level="debug" if debug else "info",
            ws_ping_interval=None,
            ws_ping_timeout=None,
        )
        # uvicorn.Config.__init__ runs dictConfig and resets the uvicorn logger
        # handlers, so the log file handler must attach after it.
        log_path = _attach_server_file_logging(debug=debug)
        log_debug(f"[server] log file: {log_path}", debug_type=DebugType.EXECUTION)
        server = _QuietServer(config)

        def _trigger_exit() -> None:
            server.should_exit = True

        lifecycle.bind_exit_trigger(_trigger_exit)

        try:
            log_debug(f"[server] starting uvicorn uds={socket_path}", debug_type=DebugType.EXECUTION)
            await server.serve()
            log_debug("[server] uvicorn server.serve() returned", debug_type=DebugType.EXECUTION)
        finally:
            log_debug("[server] cleanup start: live events", debug_type=DebugType.EXECUTION)
            await live_events.aclose()
            log_debug("[server] cleanup done: live events", debug_type=DebugType.EXECUTION)
            # Interrupts running agents and waits for session flush to disk.
            log_debug("[server] cleanup start: app components", debug_type=DebugType.EXECUTION)
            await cleanup_app_components(components)
            log_debug("[server] cleanup done: app components", debug_type=DebugType.EXECUTION)
            socket_path.unlink(missing_ok=True)
        return lifecycle.reload_requested
    finally:
        lock.release()
