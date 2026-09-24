from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch

import klaude_code.update as update
from klaude_code.cli import self_update


def test_print_version_uses_display_version(monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(update, "get_display_version", lambda: "1.2.3 (editable)")

    self_update.version_command()

    assert capsys.readouterr().out == "klaude-code 1.2.3 (editable)\n"


def test_upgrade_command_reports_git_check_failure(monkeypatch: MonkeyPatch) -> None:
    def fail() -> None:
        raise RuntimeError("git fetch origin main failed; update status is unknown")

    monkeypatch.setattr(update, "check_for_updates_blocking", fail)
    with pytest.raises(self_update.typer.Exit) as exc:
        self_update.upgrade_command(check=True)
    assert exc.value.exit_code == 1
