from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

import klaude_code.update as update


def _fake_which(name: str) -> str:
    return f"/usr/bin/{name}"


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


def test_perform_auto_upgrade_if_needed_runs_pypi_upgrade(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    del isolated_home

    monkeypatch.delenv(update.AUTO_UPGRADE_DONE_ENV, raising=False)
    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_INDEX,
        )
    )
    monkeypatch.setattr(
        update,
        "get_installation_info",
        lambda: update.InstallationInfo(version="1.0.0", install_kind=update.INSTALL_KIND_INDEX, source_url=None),
    )

    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(update.shutil, "which", _fake_which)
    monkeypatch.setattr(update.subprocess, "run", _fake_run)

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is True
    assert result.new_version == "1.1.0"
    assert calls and calls[0][:3] == ["uv", "tool", "upgrade"]
    assert not (Path.home() / ".klaude" / update.UPDATE_STATE_FILE).exists()


def test_perform_auto_upgrade_if_needed_skips_when_already_current(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home

    monkeypatch.delenv(update.AUTO_UPGRADE_DONE_ENV, raising=False)
    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_INDEX,
        )
    )
    monkeypatch.setattr(
        update,
        "get_installation_info",
        lambda: update.InstallationInfo(version="1.1.0", install_kind=update.INSTALL_KIND_INDEX, source_url=None),
    )

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is False


def test_perform_auto_upgrade_if_needed_respects_done_env(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    del isolated_home

    monkeypatch.setenv(update.AUTO_UPGRADE_DONE_ENV, "1")
    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_INDEX,
        )
    )

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is False


def test_auto_upgrade_local_git_skips_when_dirty(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home

    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.delenv(update.AUTO_UPGRADE_DONE_ENV, raising=False)
    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_LOCAL,
        )
    )
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

    def _fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["git", "-C"] and "status" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=" M README.md\n", stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(update.subprocess, "run", _fake_run)

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is False
    assert result.message is not None
    assert "uncommitted" in result.message
    # State file should still exist since upgrade did not run
    assert (Path.home() / ".klaude" / update.UPDATE_STATE_FILE).exists()


def test_auto_upgrade_local_git_runs_when_clean(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path, tmp_path: Path
) -> None:
    del isolated_home

    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.delenv(update.AUTO_UPGRADE_DONE_ENV, raising=False)
    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="1.0.0",
            latest="1.1.0",
            update_available=True,
            install_kind=update.INSTALL_KIND_EDITABLE,
        )
    )
    monkeypatch.setattr(
        update,
        "get_installation_info",
        lambda: update.InstallationInfo(
            version="1.0.0",
            install_kind=update.INSTALL_KIND_EDITABLE,
            source_url=f"file://{repo}",
        ),
    )
    monkeypatch.setattr(update, "get_install_source_path", lambda: str(repo))
    monkeypatch.setattr(update.shutil, "which", _fake_which)

    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(update.subprocess, "run", _fake_run)

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is True
    assert result.new_version == "1.1.0"
    # Expect status, pull, install in order
    assert any("status" in c for c in calls)
    assert any("pull" in c for c in calls)
    assert any(c[:3] == ["uv", "tool", "install"] and "--editable" in c for c in calls)
