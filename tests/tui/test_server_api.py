"""Tests for the server code-staleness check used after config saves."""

from __future__ import annotations

from unittest.mock import patch

from klaude_code.tui.client import server_api


def _status_body(fingerprint: str = "git:aaa", protocol: int | None = 1) -> dict[str, object]:
    return {"code_fingerprint": fingerprint, "protocol_version": protocol}


class TestServerCodeIsStale:
    def test_matching_fingerprint_is_not_stale(self) -> None:
        with (
            patch.object(server_api, "_request", return_value=_status_body("git:aaa")),
            patch("klaude_code.update.get_code_fingerprint", return_value="git:aaa"),
        ):
            assert server_api.server_code_is_stale() is False

    def test_different_fingerprint_is_stale(self) -> None:
        with (
            patch.object(server_api, "_request", return_value=_status_body("git:old")),
            patch("klaude_code.update.get_code_fingerprint", return_value="git:new"),
        ):
            assert server_api.server_code_is_stale() is True

    def test_unreachable_server_is_not_stale(self) -> None:
        with patch.object(server_api, "_request", side_effect=RuntimeError("no server")):
            assert server_api.server_code_is_stale() is False
