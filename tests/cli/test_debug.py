from pathlib import Path

import pytest

from klaude_code.cli.debug import prepare_debug_logging


def test_debug_disabled_does_not_touch_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.log.set_debug_logging", lambda *_: pytest.fail("Debug should stay disabled"))
    assert prepare_debug_logging(False) == (False, None)


def test_debug_uses_current_process(monkeypatch: pytest.MonkeyPatch) -> None:
    enabled = []
    monkeypatch.setattr("klaude_code.log.set_debug_logging", enabled.append)
    monkeypatch.setattr("klaude_code.log.get_current_log_file", lambda: Path("/tmp/local-debug.log"))
    assert prepare_debug_logging(True) == (True, Path("/tmp/local-debug.log"))
    assert enabled == [True]
