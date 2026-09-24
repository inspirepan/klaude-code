from __future__ import annotations

import fcntl
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import klaude_code.update as update
from klaude_code.cli import self_update


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
    writer = tmp_path / "writer"
    subprocess.run(["git", "init", "-q", "-b", "main", str(writer)], check=True)
    _git(writer, "config", "user.name", "Test")
    _git(writer, "config", "user.email", "test@example.com")
    (writer / "pyproject.toml").write_text('[project]\nname = "klaude-code"\nversion = "1.2.3"\n')
    (writer / "src.txt").write_text("old")
    (writer / "stable.txt").write_text("old")
    (writer / "src" / "klaude_code").mkdir(parents=True)
    (writer / "src" / "klaude_code" / "__init__.py").write_text("")
    _git(writer, "add", ".")
    _git(writer, "commit", "-qm", "initial")
    _git(writer, "remote", "add", "origin", str(origin))
    _git(writer, "push", "-q", "origin", "main")
    repo = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(origin), str(repo)], check=True)
    (writer / "src.txt").write_text("new")
    _git(writer, "add", ".")
    _git(writer, "commit", "-qm", "update")
    _git(writer, "push", "-q", "origin", "main")
    return repo


def _fake_uv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, install_fails: bool = False, version: str = "1.2.3"
) -> list[list[str]]:
    real_run = subprocess.run
    tool_dir = tmp_path / "tools"
    entry = tool_dir / "klaude-code" / "bin" / "klaude"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("#!/bin/sh\n")
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["uv", "tool", "install"]:
            return subprocess.CompletedProcess(args, 1 if install_fails else 0, stdout="", stderr="")
        if args == ["uv", "tool", "dir"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"{tool_dir}\n", stderr="")
        if args == [str(entry), "--version"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"klaude-code {version}\n", stderr="")
        if args[0] == str(entry.parent / "python"):
            source = next((item[-1] for item in calls if item[:3] == ["uv", "tool", "install"]), "")
            module = Path(source) / "src" / "klaude_code" / "__init__.py"
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    {
                        "version": version,
                        "url": Path(source).as_uri(),
                        "entry": ["klaude_code.cli.main:app"],
                        "module": str(module),
                    }
                ),
                stderr="",
            )
        return real_run(args, **kwargs)

    monkeypatch.setattr(update.subprocess, "run", run)
    return calls


def test_git_upgrade_stashes_untracked_and_restores_after_verification(
    checkout: Path, isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    (checkout / "local.txt").write_text("keep me")
    (checkout / "stable.txt").write_text("local edit")
    calls = _fake_uv(monkeypatch, tmp_path)
    result = update._upgrade_git_install(update.INSTALL_KIND_LOCAL, str(checkout))
    assert result.performed, result.message
    assert (checkout / "local.txt").read_text() == "keep me"
    assert (checkout / "stable.txt").read_text() == "local edit"
    assert any(args[:3] == ["uv", "tool", "install"] for args in calls)
    assert _git(checkout, "stash", "list") == ""
    assert not list((Path.home() / ".klaude" / "updates").glob("*.json"))


def test_git_upgrade_retries_install_without_losing_stash(
    checkout: Path, isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    (checkout / "local.txt").write_text("keep me")
    _fake_uv(monkeypatch, tmp_path, install_fails=True)
    first = update._upgrade_git_install(update.INSTALL_KIND_EDITABLE, str(checkout))
    assert not first.performed and "reinstall failed" in (first.message or "")
    assert _git(checkout, "stash", "list")
    assert list((Path.home() / ".klaude" / "updates").glob("*.json"))
    _git(checkout, "remote", "set-url", "origin", "/missing/upstream")
    _fake_uv(monkeypatch, tmp_path)
    second = update._upgrade_git_install(update.INSTALL_KIND_EDITABLE, str(checkout))
    assert second.performed, second.message
    assert (checkout / "local.txt").read_text() == "keep me"


def test_auto_upgrade_recovers_without_cached_update(
    checkout: Path, isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    (checkout / "local.txt").write_text("keep me")
    _fake_uv(monkeypatch, tmp_path, install_fails=True)
    assert not update._upgrade_git_install(update.INSTALL_KIND_LOCAL, str(checkout)).performed
    _fake_uv(monkeypatch, tmp_path)
    monkeypatch.delenv(update.AUTO_UPGRADE_DONE_ENV, raising=False)
    monkeypatch.setattr(
        update,
        "get_installation_info",
        lambda: update.InstallationInfo("1.2.3", update.INSTALL_KIND_LOCAL, checkout.as_uri()),
    )
    result = update.perform_auto_upgrade_if_needed()
    assert result.performed, result.message
    assert (checkout / "local.txt").read_text() == "keep me"


def test_cli_recovers_after_fetch_check_fails(
    checkout: Path, isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    _fake_uv(monkeypatch, tmp_path, install_fails=True)
    assert not update._upgrade_git_install(update.INSTALL_KIND_LOCAL, str(checkout)).performed
    _fake_uv(monkeypatch, tmp_path)
    _git(checkout, "remote", "set-url", "origin", "/missing/upstream")
    monkeypatch.setattr(
        update,
        "get_installation_info",
        lambda: update.InstallationInfo("1.2.3", update.INSTALL_KIND_LOCAL, checkout.as_uri()),
    )
    monkeypatch.setattr(update, "check_for_updates_blocking", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(self_update, "_upgrade_via_server", lambda: False)
    self_update.upgrade_command(check=False)
    assert not update._git_upgrade_marker(str(checkout)).exists()


def test_git_upgrade_refuses_concurrent_lock(
    checkout: Path, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    monkeypatch.setattr(update.shutil, "which", lambda _: "/usr/bin/tool")
    key = update.hashlib.sha256(str(checkout.resolve()).encode()).hexdigest()[:24]
    path = Path.home() / ".klaude" / "updates" / f"{key}.lock"
    path.parent.mkdir(parents=True)
    with path.open("a+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = update._upgrade_git_install(update.INSTALL_KIND_LOCAL, str(checkout))
    assert not result.performed and "already running" in (result.message or "")


def test_git_upgrade_keeps_stash_after_restore_conflict(
    checkout: Path, isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    (checkout / "src.txt").write_text("conflicting edit")
    _fake_uv(monkeypatch, tmp_path)
    result = update._upgrade_git_install(update.INSTALL_KIND_LOCAL, str(checkout))
    assert not result.performed and "preserved" in (result.message or "")
    assert _git(checkout, "stash", "list")
    marker = update._git_upgrade_marker(str(checkout))
    assert json.loads(marker.read_text())["phase"] == "restore"
    retry = update._upgrade_git_install(update.INSTALL_KIND_LOCAL, str(checkout))
    assert not retry.performed and "manual restoration" in (retry.message or "")


def test_git_upgrade_rejects_stale_installed_entry(
    checkout: Path, isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    _fake_uv(monkeypatch, tmp_path, version="0.0.0")
    result = update._upgrade_git_install(update.INSTALL_KIND_LOCAL, str(checkout))
    assert not result.performed and "version check" in (result.message or "")
    assert update._git_upgrade_marker(str(checkout)).exists()


def test_git_upgrade_does_not_move_head_when_stash_fails(
    checkout: Path, isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del isolated_home
    (checkout / "new.txt").write_text("keep me")
    _git(checkout, "add", "-N", "new.txt")
    before = _git(checkout, "rev-parse", "HEAD")
    monkeypatch.setattr(update.shutil, "which", lambda _: "/usr/bin/tool")
    result = update._upgrade_git_install(update.INSTALL_KIND_LOCAL, str(checkout))
    assert not result.performed and "Stash failed" in (result.message or "")
    assert _git(checkout, "rev-parse", "HEAD") == before
    assert (checkout / "new.txt").read_text() == "keep me"


def test_git_check_fetch_failure_never_uses_stale_ref(checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(checkout, "remote", "set-url", "origin", "/missing/upstream")
    monkeypatch.setattr(update.shutil, "which", lambda _: "/usr/bin/git")
    with pytest.raises(RuntimeError, match="status is unknown"):
        update._fetch_git_version_info(update.InstallationInfo("1.2.3", update.INSTALL_KIND_LOCAL, None), str(checkout))
