from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import signal
import threading
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import uvicorn
import uvicorn.server

from klaude_code.app.runtime import AppInitConfig, cleanup_app_components, initialize_app_components
from klaude_code.control.event_relay import event_relay_socket_path
from klaude_code.control.session_meta_relay import session_meta_relay_socket_path
from klaude_code.log import DebugType, log, log_debug
from klaude_code.update import INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL, get_installation_info
from klaude_code.web.app import create_app
from klaude_code.web.display import WebDisplay
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.live_events import start_web_live_events


@dataclass(frozen=True)
class FrontendLaunchPlan:
    url: str
    process: asyncio.subprocess.Process | None
    mode: str


class WebServerAlreadyRunningError(RuntimeError):
    """Raised when another web server instance is already active for this home directory."""


def _browser_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _find_pkg_manager() -> str | None:
    """Return the best available JS package manager command, or None."""
    for cmd in ("pnpm", "npm"):
        if shutil.which(cmd) is not None:
            return cmd
    return None


def _can_start_frontend_dev_server(project_root: Path) -> bool:
    web_dir = project_root / "web"
    package_json = web_dir / "package.json"
    return package_json.exists() and _find_pkg_manager() is not None


def _should_auto_install_frontend(project_root: Path) -> bool:
    if not _can_start_frontend_dev_server(project_root):
        return False

    install_kind = get_installation_info().install_kind
    return install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL}


def _frontend_dependencies_installed(web_dir: Path) -> bool:
    package_json = web_dir / "package.json"
    if not package_json.exists():
        return True

    try:
        package_data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return True
    if not isinstance(package_data, dict):
        return True
    package_json_data = cast(dict[str, object], package_data)

    dependency_groups: list[object | None] = [
        package_json_data.get("dependencies"),
        package_json_data.get("devDependencies"),
    ]
    for group_data in dependency_groups:
        if not isinstance(group_data, dict):
            continue
        group = cast(dict[str, object], group_data)
        for package_name in group:
            if not (web_dir / "node_modules" / package_name).exists():
                return False
    return True


def _http_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1):
            return True
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


async def _wait_until_ready(url: str, timeout_s: float = 10.0) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if await asyncio.to_thread(_http_ready, url):
            return True
        await asyncio.sleep(0.2)
    return False


async def _terminate_process(process: asyncio.subprocess.Process | None) -> None:
    if process is None:
        return
    if process.returncode is not None:
        return
    process.terminate()
    try:
        _ = await asyncio.wait_for(process.wait(), timeout=3.0)
    except TimeoutError:
        process.kill()
        with contextlib.suppress(TimeoutError):
            _ = await asyncio.wait_for(process.wait(), timeout=1.0)


async def _install_frontend_dependencies(web_dir: Path, pkg_manager: str) -> bool:
    install_args = [pkg_manager, "install"]
    if pkg_manager == "pnpm" and (web_dir / "pnpm-lock.yaml").exists():
        install_args.append("--frozen-lockfile")

    process = await asyncio.create_subprocess_exec(*install_args, cwd=str(web_dir))
    return (await process.wait()) == 0


async def _start_frontend_dev_process(
    *, web_dir: Path, host: str, frontend_port: int, pkg_manager: str
) -> asyncio.subprocess.Process:
    # npm needs "--" to separate its own flags from script args; pnpm v10+ does
    # not strip "--" and passes it verbatim to the script, which breaks vite.
    separator: list[str] = ["--"] if pkg_manager == "npm" else []
    return await asyncio.create_subprocess_exec(
        pkg_manager,
        "run",
        "dev",
        *separator,
        "--host",
        host,
        "--port",
        str(frontend_port),
        "--strictPort",
        cwd=str(web_dir),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def prepare_frontend(
    *,
    host: str,
    backend_port: int,
) -> FrontendLaunchPlan:
    browser_host = _browser_host(host)
    backend_url = f"http://{browser_host}:{backend_port}/"
    project_root = _project_root()
    if not _can_start_frontend_dev_server(project_root):
        return FrontendLaunchPlan(url=backend_url, process=None, mode="static")

    pkg_manager = _find_pkg_manager()
    assert pkg_manager is not None  # guaranteed by _can_start_frontend_dev_server

    frontend_port = backend_port + 1
    web_dir = project_root / "web"
    frontend_url = f"http://{browser_host}:{frontend_port}/"

    if _should_auto_install_frontend(project_root) and not _frontend_dependencies_installed(web_dir):
        log(f"Frontend dependencies are incomplete. Running `{pkg_manager} install` once...")
        if not await _install_frontend_dependencies(web_dir, pkg_manager):
            return FrontendLaunchPlan(url=backend_url, process=None, mode="static")

    attempts = 2 if _should_auto_install_frontend(project_root) else 1
    for attempt in range(attempts):
        process = await _start_frontend_dev_process(
            web_dir=web_dir, host=host, frontend_port=frontend_port, pkg_manager=pkg_manager
        )
        if process.returncode is not None:
            await _terminate_process(process)
        else:
            ready = await _wait_until_ready(frontend_url, timeout_s=10.0)
            if ready:
                return FrontendLaunchPlan(url=frontend_url, process=process, mode="dev")
            await _terminate_process(process)

        if attempt == 0 and attempts > 1:
            log(f"Frontend dev server did not start. Running `{pkg_manager} install` once...")
            if not await _install_frontend_dependencies(web_dir, pkg_manager):
                break

    return FrontendLaunchPlan(url=backend_url, process=None, mode="static")


def open_browser(url: str, *, no_open: bool) -> None:
    if no_open:
        return
    _ = webbrowser.open(url)


async def _is_unix_socket_live(socket_path: Path) -> bool:
    if not socket_path.exists():
        return False
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
    except OSError:
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    del reader
    return True


async def _ensure_web_server_not_running(*, home_dir: Path) -> None:
    socket_conflicts: list[str] = []

    event_socket = event_relay_socket_path(home_dir=home_dir)
    if await _is_unix_socket_live(event_socket):
        socket_conflicts.append(f"event relay socket already in use: {event_socket}")

    session_meta_socket = session_meta_relay_socket_path(home_dir=home_dir)
    if await _is_unix_socket_live(session_meta_socket):
        socket_conflicts.append(f"session meta relay socket already in use: {session_meta_socket}")

    if socket_conflicts:
        raise WebServerAlreadyRunningError("Web server is already running:\n" + "\n".join(socket_conflicts))


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
                signal.signal(sig, handler)


async def start_web_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    no_open: bool = False,
    debug: bool = False,
) -> None:
    home_dir = Path.home()
    await _ensure_web_server_not_running(home_dir=home_dir)

    interaction_handler = WebInteractionHandler()
    components = await initialize_app_components(
        init_config=AppInitConfig(
            model=None,
            debug=debug,
            vanilla=False,
            runtime_kind="web",
            enable_event_relay_client=False,
        ),
        display=WebDisplay(),
        interaction_handler=None,
    )
    live_events = await start_web_live_events(components.event_bus, home_dir=home_dir)
    if live_events.relay_error is not None:
        log((f"Cross-process live events unavailable: {live_events.relay_error}", "yellow"))

    app = create_app(
        runtime=components.runtime,
        event_bus=components.event_bus,
        event_stream=live_events.stream,
        interaction_handler=interaction_handler,
        work_dir=Path.cwd(),
        home_dir=home_dir,
    )

    frontend_plan = await prepare_frontend(host=host, backend_port=port)
    open_browser(frontend_plan.url, no_open=no_open)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
        ws_ping_interval=None,
        ws_ping_timeout=None,
    )
    server = _QuietServer(config)
    try:
        log_debug(f"[web] starting uvicorn host={host} port={port}", debug_type=DebugType.EXECUTION)
        await server.serve()
        log_debug("[web] uvicorn server.serve() returned", debug_type=DebugType.EXECUTION)
    finally:
        log_debug("[web] cleanup start: frontend process", debug_type=DebugType.EXECUTION)
        await _terminate_process(frontend_plan.process)
        log_debug("[web] cleanup done: frontend process", debug_type=DebugType.EXECUTION)
        log_debug("[web] cleanup start: live events", debug_type=DebugType.EXECUTION)
        await live_events.aclose()
        log_debug("[web] cleanup done: live events", debug_type=DebugType.EXECUTION)
        log_debug("[web] cleanup start: app components", debug_type=DebugType.EXECUTION)
        await cleanup_app_components(components)
        log_debug("[web] cleanup done: app components", debug_type=DebugType.EXECUTION)
    remaining_tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]
    log_debug(
        f"[web] start_web_server returning remaining_tasks={len(remaining_tasks)}", debug_type=DebugType.EXECUTION
    )
