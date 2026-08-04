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


def test_start_background_auto_upgrade_if_needed_starts_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"thread_started": 0, "upgrade_runs": 0}

    class _FakeThread:
        def __init__(
            self,
            *,
            target: Callable[[], None],
            name: str | None = None,
            daemon: bool | None = None,
        ) -> None:
            self._target = target
            self.name = name
            self.daemon = daemon

        def start(self) -> None:
            calls["thread_started"] += 1
            assert self.name == "auto-upgrade"
            assert self.daemon is True
            self._target()

    def _fake_perform_auto_upgrade_if_needed() -> None:
        calls["upgrade_runs"] += 1

    monkeypatch.setattr(update, "perform_auto_upgrade_if_needed", _fake_perform_auto_upgrade_if_needed)
    monkeypatch.setattr(update.threading, "Thread", _FakeThread)
    monkeypatch.setattr(update, "_background_auto_upgrade_in_progress", False)

    update.start_background_auto_upgrade_if_needed()

    assert calls == {"thread_started": 1, "upgrade_runs": 1}
    assert update._background_auto_upgrade_in_progress is False


def test_start_background_auto_upgrade_if_needed_skips_duplicate_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "_background_auto_upgrade_in_progress", True)
    monkeypatch.setattr(update.threading, "Thread", lambda **_: (_ for _ in ()).throw(AssertionError("unexpected")))

    update.start_background_auto_upgrade_if_needed()


def test_run_background_auto_upgrade_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []

    def _raise() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(update, "perform_auto_upgrade_if_needed", _raise)
    monkeypatch.setattr(update, "_background_auto_upgrade_in_progress", True)
    monkeypatch.setattr("klaude_code.log.log_debug", lambda message: messages.append(message))

    update._run_background_auto_upgrade()

    assert update._background_auto_upgrade_in_progress is False
    assert messages == ["Background auto-upgrade failed: boom"]


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
    monkeypatch.setattr(update.subprocess, "run", _make_fake_run(calls))

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is True
    assert result.new_version == "1.1.0"
    # Expect status, branch check, pull, submodule sync, install in order
    assert any("status" in c and "--ignore-submodules=all" in c for c in calls)
    assert any("pull" in c for c in calls)
    assert any("submodule" in c for c in calls)
    assert any(c[:3] == ["uv", "tool", "install"] and "--editable" in c for c in calls)


def test_auto_upgrade_local_git_stops_when_submodule_sync_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(update.shutil, "which", _fake_which)

    calls: list[list[str]] = []

    def fake_run_git(repo_path: str, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        del repo_path, timeout
        calls.append(args)
        if "--abbrev-ref" in args:
            return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
        if "submodule" in args:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="failed")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(update, "_run_git", fake_run_git)

    result = update._auto_upgrade_local_git(update.INSTALL_KIND_LOCAL, str(repo))

    assert result.performed is False
    assert result.level == "warn"
    assert result.message is not None
    assert "submodule update" in result.message
    assert not any(call[:3] == ["uv", "tool", "install"] for call in calls)


def test_auto_upgrade_local_git_skips_when_not_on_main(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path, tmp_path: Path
) -> None:
    """A local dev on a feature branch must not be yanked onto main."""

    del isolated_home

    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.delenv(update.AUTO_UPGRADE_DONE_ENV, raising=False)
    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="1.0.0",
            latest="abc1234",
            update_available=True,
            install_kind=update.INSTALL_KIND_EDITABLE,
            update_source=update.UPDATE_SOURCE_GIT,
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
    monkeypatch.setattr(update.subprocess, "run", _make_fake_run(calls, branch="my-feature"))

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is False
    assert result.message is not None
    assert "my-feature" in result.message
    assert not any("pull" in c for c in calls)


def test_auto_upgrade_git_source_does_not_version_compare_sha(
    monkeypatch: pytest.MonkeyPatch, isolated_home: Path, tmp_path: Path
) -> None:
    """A git-tracked checkout upgrades on commit distance, not version ordering."""

    del isolated_home

    repo = tmp_path / "repo"
    repo.mkdir()

    monkeypatch.delenv(update.AUTO_UPGRADE_DONE_ENV, raising=False)
    update.write_persisted_update_info(
        update.PersistedUpdateInfo(
            checked_at=time.time(),
            installed="2.32.0 (deadbee)",
            # Same released version as installed: the PyPI path would bail here.
            latest="abc1234",
            update_available=True,
            install_kind=update.INSTALL_KIND_EDITABLE,
            update_source=update.UPDATE_SOURCE_GIT,
        )
    )
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
    monkeypatch.setattr(update.subprocess, "run", _make_fake_run(calls))

    result = update.perform_auto_upgrade_if_needed()
    assert result.performed is True
    assert result.message is not None
    assert "origin/main abc1234" in result.message


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
