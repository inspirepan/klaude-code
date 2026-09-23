"""Tests for the UDS client's env-sync header."""

from __future__ import annotations

from pathlib import Path

import pytest

import klaude_code.cli.uds_client as uds_client
from klaude_code.protocol.env_sync import decode_env_header


class _FakeConfig:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def referenced_env_values(self) -> dict[str, str]:
        return self._values


def test_client_env_header_carries_only_referenced_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "klaude_code.config.load_config",
        lambda: _FakeConfig({"KLAUDE_REF_A": "value-a", "KLAUDE_REF_UNSET": ""}),
    )
    uds_client._client_env_header.cache_clear()  # pyright: ignore[reportPrivateUsage]

    header = uds_client._client_env_header()  # pyright: ignore[reportPrivateUsage]

    assert header is not None
    assert decode_env_header(header) == {"KLAUDE_REF_A": "value-a", "KLAUDE_REF_UNSET": ""}


def test_client_env_header_is_none_without_referenced_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.config.load_config", lambda: _FakeConfig({}))
    uds_client._client_env_header.cache_clear()  # pyright: ignore[reportPrivateUsage]

    assert uds_client._client_env_header() is None


def test_client_env_header_survives_config_load_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken_load() -> object:
        raise RuntimeError("broken config")

    monkeypatch.setattr("klaude_code.config.load_config", _broken_load)
    uds_client._client_env_header.cache_clear()  # pyright: ignore[reportPrivateUsage]

    assert uds_client._client_env_header() is None


class _ExitedProcess:
    def poll(self) -> int:
        return 2


def test_autostart_reports_boot_failure_without_waiting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from klaude_code.server.startup_log import server_startup_log_path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    log_path = server_startup_log_path()
    log_path.parent.mkdir(parents=True)
    log_path.write_text("Error: failed to load config: Unknown model: gpt-5.6-luna@codex\n")

    def _down(*_args: object, **_kwargs: object) -> tuple[int, object]:
        raise uds_client.ServerNotRunningError("socket")

    monkeypatch.setattr(uds_client, "request", _down)
    monkeypatch.setattr(uds_client, "_spawn_server_detached", _ExitedProcess)
    monkeypatch.setattr(uds_client.time, "sleep", lambda _s: None)

    with pytest.raises(uds_client.ServerNotRunningError) as exc_info:
        uds_client.ensure_server_running(startup_timeout=60.0)

    message = str(exc_info.value)
    assert "exited during startup (code 2)" in message
    assert "Unknown model: gpt-5.6-luna@codex" in message


def test_startup_log_redirect_is_noop_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.server import startup_log

    monkeypatch.delenv(startup_log.STARTUP_LOG_ENV, raising=False)
    # Must not touch this process's stdout/stderr.
    startup_log.redirect_output_to_startup_log()
    startup_log.detach_output_from_startup_log()
