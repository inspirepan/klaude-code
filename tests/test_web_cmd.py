from __future__ import annotations

from collections.abc import Coroutine
from types import SimpleNamespace

import pytest
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
