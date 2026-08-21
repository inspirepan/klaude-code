"""Tests for the UDS client's env-sync header."""

from __future__ import annotations

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
