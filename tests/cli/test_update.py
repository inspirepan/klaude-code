from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

import klaude_code.update as update


def _fake_which(name: str) -> str:
    return f"/usr/bin/{name}"


def _make_fake_run(
    calls: list[list[str]],
    *,
    branch: str = "main",
    head: str = "deadbee",
    remote: str = "abc1234",
    behind: str = "2",
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Fake ``subprocess.run`` that answers the git queries the updater makes."""

    def _fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        stdout = ""
        if "rev-parse" in cmd:
            if "--abbrev-ref" in cmd:
                stdout = branch
            elif "--git-dir" in cmd:
                stdout = ".git"
            elif "HEAD" in cmd:
                stdout = head
            else:
                stdout = remote
        elif "rev-list" in cmd:
            stdout = behind
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return _fake_run


def test_run_git_disables_terminal_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    monkeypatch.setattr(update.subprocess, "run", fake_run)

    result = update._run_git("/repo", ["status"], 10)

    assert result is not None
    assert captured["stdin"] == subprocess.DEVNULL
    env = cast(dict[str, str], captured["env"])
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_get_startup_update_summary_without_state_starts_background_check(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home

    started = {"value": False}

    def _fake_start_background_update_check() -> None:
        started["value"] = True

    monkeypatch.setattr(update, "_start_background_update_check", _fake_start_background_update_check)

    assert update.get_startup_update_summary() is None
    assert started["value"] is True


def test_persist_current_update_info_writes_state_file(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    del isolated_home

    monkeypatch.setattr(
        update,
        "_fetch_version_info",
        lambda: update.VersionInfo(
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_INDEX,
        ),
    )

    update.persist_current_update_info()

    path = Path.home() / ".klaude" / update.UPDATE_STATE_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["installed"] == "1.0.0"
    assert payload["latest"] == "1.1.0"
    assert payload["update_available"] is True
    assert payload["install_kind"] == update.INSTALL_KIND_INDEX


def test_get_startup_update_summary_returns_message_from_persisted_state(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home

    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_LOCAL,
        )
    )

    started = {"value": False}

    def _fake_start_background_update_check() -> None:
        started["value"] = True

    monkeypatch.setattr(update, "_start_background_update_check", _fake_start_background_update_check)

    summary = update.get_startup_update_summary()
    assert summary is not None
    assert summary.level == "warn"
    assert summary.message == (
        "PyPI 1.1.0 available. Current 1.0.0 (local path install); run `klaude upgrade` from a clean local checkout."
    )
    assert started["value"] is False


def test_get_startup_update_summary_refreshes_stale_state_in_background(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home

    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time() - update.CHECK_INTERVAL_SECONDS - 1,
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_EDITABLE,
        )
    )

    started = {"value": False}

    def _fake_start_background_update_check() -> None:
        started["value"] = True

    monkeypatch.setattr(update, "_start_background_update_check", _fake_start_background_update_check)

    summary = update.get_startup_update_summary()
    assert summary is not None
    assert "editable install" in summary.message
    assert started["value"] is True


def test_fetch_version_info_tracks_git_for_editable_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr(
        update,
        "get_installation_info",
        lambda: update.InstallationInfo(
            version="2.32.0",
            install_kind=update.INSTALL_KIND_EDITABLE,
            source_url=f"file://{repo}",
        ),
    )
    monkeypatch.setattr(update, "get_install_source_path", lambda: str(repo))
    monkeypatch.setattr(update.shutil, "which", _fake_which)

    calls: list[list[str]] = []
    monkeypatch.setattr(update.subprocess, "run", _make_fake_run(calls, behind="3", head="deadbee"))

    def _unreachable() -> str | None:
        raise AssertionError("PyPI must not be consulted for a git-tracked checkout")

    monkeypatch.setattr(update, "_get_latest_version", _unreachable)

    info = update._fetch_version_info()
    assert info is not None
    assert info.update_source == update.UPDATE_SOURCE_GIT
    assert info.update_available is True
    assert info.latest == "abc1234"
    assert info.installed == "2.32.0 (deadbee)"
    assert any("fetch" in c for c in calls)


def test_fetch_version_info_falls_back_to_pypi_when_source_not_a_git_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.setattr(
        update,
        "get_installation_info",
        lambda: update.InstallationInfo(
            version="1.0.0",
            install_kind=update.INSTALL_KIND_LOCAL,
            source_url=f"file://{repo}",
        ),
    )
    monkeypatch.setattr(update, "get_install_source_path", lambda: str(repo))
    monkeypatch.setattr(update.shutil, "which", _fake_which)
    monkeypatch.setattr(update, "_get_latest_version", lambda: "1.1.0")

    def _not_a_repo(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="not a git repository")

    monkeypatch.setattr(update.subprocess, "run", _not_a_repo)

    info = update._fetch_version_info()
    assert info is not None
    assert info.update_source == update.UPDATE_SOURCE_PYPI
    assert info.latest == "1.1.0"
    assert info.update_available is True
