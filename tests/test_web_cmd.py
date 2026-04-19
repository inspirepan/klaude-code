from __future__ import annotations

from collections.abc import Coroutine
from types import SimpleNamespace
from typing import cast

import pytest
import typer
from typer.testing import CliRunner

pytestmark = pytest.mark.usefixtures("isolated_home")


def test_web_command_exits_cleanly_on_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.cli.main import app
    from klaude_code.web import server as web_server

    async def _start_web_server(**_kwargs: object) -> None:
        return None

    def _raise_keyboard_interrupt(coro: Coroutine[object, object, None]) -> None:
        coro.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(web_server, "start_web_server", _start_web_server)
    monkeypatch.setattr("klaude_code.cli.web_cmd.asyncio", SimpleNamespace(run=_raise_keyboard_interrupt))

    result = CliRunner().invoke(app, ["web", "--no-open"])

    assert result.exit_code == 130
    assert "Traceback" not in result.output


def test_web_command_exits_cleanly_when_server_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.cli.main import app
    from klaude_code.web import server as web_server

    async def _start_web_server(**_kwargs: object) -> None:
        raise web_server.WebServerAlreadyRunningError(
            "Web server is already running:\nsession meta relay socket already in use: /tmp/klaude.sock"
        )

    monkeypatch.setattr(web_server, "start_web_server", _start_web_server)

    result = CliRunner().invoke(app, ["web", "--no-open"])

    assert result.exit_code == 0
    assert "Web server is already running" in result.output
    assert "Traceback" not in result.output


def test_main_callback_starts_web_mode_after_tui_returns_request(monkeypatch: pytest.MonkeyPatch) -> None:
    import klaude_code.config as config_module
    import klaude_code.tui.runner as tui_runner
    from klaude_code.cli import main as cli_main
    from klaude_code.tui.command.command_abc import WebModeRequest

    requested = WebModeRequest(host="0.0.0.0", port=9000, no_open=True, debug=None)
    web_calls: list[dict[str, object]] = []

    async def _run_interactive(**_kwargs: object) -> WebModeRequest:
        return requested

    def _run_web_server_command(**kwargs: object) -> None:
        web_calls.append(dict(kwargs))

    def _prepare_debug_logging(_debug: bool) -> tuple[bool, None]:
        return True, None

    def _update_terminal_title(*_args: object, **_kwargs: object) -> None:
        return None

    def _load_config() -> SimpleNamespace:
        return SimpleNamespace(main_model="default-model")

    monkeypatch.setattr(tui_runner, "run_interactive", _run_interactive)
    monkeypatch.setattr(cli_main, "run_web_server_command", _run_web_server_command)
    monkeypatch.setattr(cli_main, "prepare_debug_logging", _prepare_debug_logging)
    monkeypatch.setattr("klaude_code.tui.terminal.title.update_terminal_title", _update_terminal_title)
    monkeypatch.setattr(cli_main.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli_main.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(config_module, "load_config", _load_config)

    cli_main.main_callback(
        ctx=cast(typer.Context, SimpleNamespace(invoked_subcommand=None)),
        model=None,
        continue_=False,
        resume=False,
        resume_by_id=None,
        select_model=False,
        debug=True,
        vanilla=False,
        version=False,
    )

    assert web_calls == [
        {
            "host": "0.0.0.0",
            "port": 9000,
            "no_open": True,
            "debug": True,
        }
    ]
