import pytest
from typer.testing import CliRunner

from klaude_code.cli.main import app


def test_web_starts_read_only_app_without_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = []
    opened = []
    marker = object()
    monkeypatch.setattr("klaude_code.server.read_only.create_read_only_app", lambda **_kwargs: marker)
    monkeypatch.setattr("uvicorn.run", lambda application, **kwargs: runs.append((application, kwargs)))
    monkeypatch.setattr("webbrowser.open", opened.append)
    result = CliRunner().invoke(app, ["web", "--port", "8877"])
    assert result.exit_code == 0, result.output
    assert opened == ["http://127.0.0.1:8877"]
    assert runs == [(marker, {"host": "127.0.0.1", "port": 8877, "log_level": "warning"})]


def test_web_no_open_and_legacy_attach_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("uvicorn.run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("webbrowser.open", lambda *_args: pytest.fail("Must not open browser"))
    result = CliRunner().invoke(app, ["web", "--no-open"])
    assert result.exit_code == 0, result.output
    assert "127.0.0.1:8765" in result.output
    assert CliRunner().invoke(app, ["attach", "old"]).exit_code == 2
    assert CliRunner().invoke(app, ["server", "run"]).exit_code == 2


def test_help_explains_local_lifetime() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "web " in result.output
    assert "independent local processes" in result.output
    assert "attach " not in result.output
