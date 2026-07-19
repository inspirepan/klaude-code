from __future__ import annotations

import pytest

from klaude_code.tui.terminal import color


@pytest.mark.parametrize("env_name", ["TMUX", "SSH_TTY", "SSH_CONNECTION"])
def test_background_detection_skips_indirect_terminals(
    env_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(env_name, "active")

    def _fail_query(*, slot: int, timeout: float) -> tuple[int, int, int] | None:
        del slot, timeout
        raise AssertionError("OSC query should be skipped")

    monkeypatch.setattr(color, "_query_color_slot", _fail_query)

    assert color.is_light_terminal_background() is None