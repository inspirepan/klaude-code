from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import klaude_code.update as update


def _fake_which(name: str) -> str:
    return f"/usr/bin/{name}"


def _init_fingerprint_repo(repo: Path) -> None:
    (repo / "src" / "klaude_code").mkdir(parents=True)
    (repo / "src" / "klaude_code" / "main.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )


def test_code_fingerprint_ignores_untracked_files_outside_runtime_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_fingerprint_repo(repo)
    before = update._compute_git_fingerprint(str(repo))

    (repo / "unrelated-data.bin").write_bytes(b"x" * (2 * 1024 * 1024))

    assert update._compute_git_fingerprint(str(repo)) == before


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


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (
            {"phase": "pending", "action": "upgrade", "active_sessions": [{"session_id": "a", "state": "running"}]},
            "klaude server will install the update and restart once 1 active session finish (/reload to check).",
        ),
        (
            {"phase": "pending", "action": "upgrade", "active_sessions": []},
            "klaude server is about to install the update and restart; this client reconnects automatically.",
        ),
        (
            {"phase": "installing", "action": "upgrade"},
            "klaude server is installing the update and restarts when done.",
        ),
        ({"phase": "failed", "action": None, "message": "uv missing"}, "klaude upgrade failed: uv missing"),
    ],
)
def test_auto_upgrade_notice_describes_server_status(
    monkeypatch: pytest.MonkeyPatch, status: dict[str, object], expected: str
) -> None:
    from klaude_code.cli import main as cli_main
    from klaude_code.cli import uds_client

    monkeypatch.setattr("klaude_code.config.load_config", lambda: SimpleNamespace(auto_upgrade=True))
    monkeypatch.setattr(update, "has_pending_update", lambda: True)
    requested: list[dict[str, object]] = []

    def fake_request(*, check: bool = False, timeout: float = 0.0) -> dict[str, object]:
        del timeout
        requested.append({"check": check})
        return status

    monkeypatch.setattr(uds_client, "request_server_upgrade", fake_request)
    notice = cli_main._maybe_start_auto_upgrade()
    assert notice is not None
    assert notice.result(timeout=5) == expected
    assert requested == [{"check": False}]


def test_auto_upgrade_skips_when_nothing_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.cli import main as cli_main

    monkeypatch.setattr("klaude_code.config.load_config", lambda: SimpleNamespace(auto_upgrade=True))
    monkeypatch.setattr(update, "has_pending_update", lambda: False)
    assert cli_main._maybe_start_auto_upgrade() is None


def test_auto_upgrade_notice_stays_unresolved_without_server(monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.cli import main as cli_main
    from klaude_code.cli import uds_client

    monkeypatch.setattr("klaude_code.config.load_config", lambda: SimpleNamespace(auto_upgrade=True))
    monkeypatch.setattr(update, "has_pending_update", lambda: True)
    monkeypatch.setattr(uds_client, "request_server_upgrade", lambda **_: None)
    notice = cli_main._maybe_start_auto_upgrade()
    assert notice is not None
    with pytest.raises(TimeoutError):
        notice.result(timeout=0.2)


def test_has_pending_update_reads_persisted_state(monkeypatch: pytest.MonkeyPatch, isolated_home: Path) -> None:
    del isolated_home
    monkeypatch.setattr(
        update, "get_installation_info", lambda: update.InstallationInfo("1.0.0", update.INSTALL_KIND_INDEX, None)
    )
    assert update.has_pending_update() is False
    update.write_persisted_update_info(
        update.PersistedUpdateInfo(time.time(), "1.0.0", "1.1.0", True, update.INSTALL_KIND_INDEX)
    )
    assert update.has_pending_update() is True


def test_perform_upgrade_with_check_persists_then_installs(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path
) -> None:
    del isolated_home
    monkeypatch.setattr(
        update,
        "check_for_updates_blocking",
        lambda: update.VersionInfo("1.0.0", "1.1.0", True, update.INSTALL_KIND_INDEX),
    )
    performed = update.AutoUpgradeResult(True, "1.1.0", "done")
    monkeypatch.setattr(update, "perform_auto_upgrade_if_needed", lambda: performed)
    assert update.perform_upgrade(check=True) == performed
    persisted = update._load_persisted_update_info()
    assert persisted is not None and persisted.latest == "1.1.0" and persisted.update_available


def test_perform_upgrade_with_check_reports_check_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise RuntimeError("offline")

    monkeypatch.setattr(update, "check_for_updates_blocking", fail)
    result = update.perform_upgrade(check=True)
    assert not result.performed
    assert result.message == "update check failed: offline"


def test_upgraded_code_fingerprint_uses_new_wheel_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        update, "get_installation_info", lambda: update.InstallationInfo("1.0.0", update.INSTALL_KIND_INDEX, None)
    )
    assert update.upgraded_code_fingerprint(update.AutoUpgradeResult(True, "1.1.0", None)) == "pkg:1.1.0"
    assert update.upgraded_code_fingerprint(update.AutoUpgradeResult(True, None, None)) is None


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
        output = "klaude-code v1.2.0\n" if cmd == ["uv", "tool", "list"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")

    monkeypatch.setattr(update.shutil, "which", _fake_which)
    monkeypatch.setattr(update.subprocess, "run", _fake_run)

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is True
    assert result.new_version == "1.2.0"
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
