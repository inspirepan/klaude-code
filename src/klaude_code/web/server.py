from __future__ import annotations

import asyncio
import contextlib
import shutil
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from klaude_code.app.runtime import AppInitConfig, cleanup_app_components, initialize_app_components
from klaude_code.log import log
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


def _browser_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _can_start_frontend_dev_server(project_root: Path) -> bool:
    web_dir = project_root / "web"
    package_json = web_dir / "package.json"
    return package_json.exists() and shutil.which("pnpm") is not None


def _should_auto_install_frontend(project_root: Path) -> bool:
    if not _can_start_frontend_dev_server(project_root):
        return False

    install_kind = get_installation_info().install_kind
    return install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL}


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


async def _install_frontend_dependencies(web_dir: Path) -> bool:
    install_args = ["pnpm", "install"]
    if (web_dir / "pnpm-lock.yaml").exists():
        install_args.append("--frozen-lockfile")

    process = await asyncio.create_subprocess_exec(*install_args, cwd=str(web_dir))
    return (await process.wait()) == 0


async def _start_frontend_dev_process(*, web_dir: Path, host: str, frontend_port: int) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        "pnpm",
        "dev",
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

    frontend_port = backend_port + 1
    web_dir = project_root / "web"
    frontend_url = f"http://{browser_host}:{frontend_port}/"

    attempts = 2 if _should_auto_install_frontend(project_root) else 1
    for attempt in range(attempts):
        process = await _start_frontend_dev_process(web_dir=web_dir, host=host, frontend_port=frontend_port)
        if process.returncode is not None:
            await _terminate_process(process)
        else:
            ready = await _wait_until_ready(frontend_url, timeout_s=10.0)
            if ready:
                return FrontendLaunchPlan(url=frontend_url, process=process, mode="dev")
            await _terminate_process(process)

        if attempt == 0 and attempts > 1:
            log("Frontend dev server did not start. Running `pnpm install --frozen-lockfile` once...")
            if not await _install_frontend_dependencies(web_dir):
                break

    return FrontendLaunchPlan(url=backend_url, process=None, mode="static")


def open_browser(url: str, *, no_open: bool) -> None:
    if no_open:
        return
    _ = webbrowser.open(url)


async def start_web_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    no_open: bool = False,
    debug: bool = False,
) -> None:
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
    live_events = await start_web_live_events(components.event_bus, home_dir=Path.home())
    if live_events.relay_error is not None:
        log((f"Cross-process live events unavailable: {live_events.relay_error}", "yellow"))

    app = create_app(
        runtime=components.runtime,
        event_bus=components.event_bus,
        event_stream=live_events.stream,
        interaction_handler=interaction_handler,
        work_dir=Path.cwd(),
        home_dir=Path.home(),
    )

    frontend_plan = await prepare_frontend(host=host, backend_port=port)
    open_browser(frontend_plan.url, no_open=no_open)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        await _terminate_process(frontend_plan.process)
        await live_events.aclose()
        await cleanup_app_components(components)
