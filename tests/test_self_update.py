from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

import klaude_code.update as update
from klaude_code.cli import self_update


class _Result:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


type _LogObject = str | tuple[str, str]


def test_upgrade_command_updates_clean_editable_local_git_checkout(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source_path = tmp_path / "klaude-code"
    source_path.mkdir()

    info = update.VersionInfo(
        installed="1.0.0",
        latest="1.1.0",
        update_available=True,
        install_kind=update.INSTALL_KIND_EDITABLE,
    )
    monkeypatch.setattr(update, "check_for_updates_blocking", lambda: info)
    monkeypatch.setattr(update, "get_install_source_path", lambda: str(source_path))

    def fake_which(cmd: str) -> str:
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr(self_update.shutil, "which", fake_which)

    calls: list[list[str]] = []
    messages: list[str] = []

    def fake_run(
        args: list[str],
        *,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
    ) -> _Result:
        assert check is False
        calls.append(args)
        if args == ["git", "-C", str(source_path), "status", "--porcelain"]:
            assert capture_output is True
            assert text is True
            return _Result(stdout="")
        return _Result()

    monkeypatch.setattr(self_update.subprocess, "run", fake_run)

    def fake_log(*objects: _LogObject) -> None:
        messages.extend(obj[0] if isinstance(obj, tuple) else obj for obj in objects)

    monkeypatch.setattr("klaude_code.log.log", fake_log)

    self_update.upgrade_command(check=False)

    assert calls == [
        ["git", "-C", str(source_path), "status", "--porcelain"],
        ["git", "-C", str(source_path), "checkout", "main"],
        ["git", "-C", str(source_path), "pull", "--ff-only"],
        ["uv", "tool", "install", "--force", "--editable", str(source_path)],
    ]
    assert "Update complete. Please re-run `klaude` to use the new version." in messages


def test_print_version_uses_display_version(monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(update, "get_display_version", lambda: "1.2.3 (editable)")

    self_update.version_command()

    assert capsys.readouterr().out == "klaude-code 1.2.3 (editable)\n"


def test_upgrade_command_rejects_dirty_local_git_checkout(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    source_path = tmp_path / "klaude-code"
    source_path.mkdir()

    info = update.VersionInfo(
        installed="1.0.0",
        latest="1.1.0",
        update_available=True,
        install_kind=update.INSTALL_KIND_LOCAL,
    )
    monkeypatch.setattr(update, "check_for_updates_blocking", lambda: info)
    monkeypatch.setattr(update, "get_install_source_path", lambda: str(source_path))

    def fake_which(cmd: str) -> str:
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr(self_update.shutil, "which", fake_which)

    calls: list[list[str]] = []
    messages: list[str] = []

    def fake_run(
        args: list[str],
        *,
        capture_output: bool = False,
        text: bool = False,
        check: bool = False,
    ) -> _Result:
        assert check is False
        calls.append(args)
        if args == ["git", "-C", str(source_path), "status", "--porcelain"]:
            assert capture_output is True
            assert text is True
            return _Result(stdout=" M src/klaude_code/update.py\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(self_update.subprocess, "run", fake_run)

    def fake_log(*objects: _LogObject) -> None:
        messages.extend(obj[0] if isinstance(obj, tuple) else obj for obj in objects)

    monkeypatch.setattr("klaude_code.log.log", fake_log)

    with pytest.raises(self_update.typer.Exit) as exc_info:
        self_update.upgrade_command(check=False)

    assert exc_info.value.exit_code == 1
    assert calls == [["git", "-C", str(source_path), "status", "--porcelain"]]
    assert "Error: local git checkout has uncommitted changes." in messages
