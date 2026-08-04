"""Version handshake: code fingerprint computation and the client-side check.

Matrix under test: fingerprint match/mismatch x server idle/busy.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from klaude_code import update
from klaude_code.cli import uds_client
from klaude_code.protocol.version import PROTOCOL_VERSION


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(repo),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    package_dir = repo / "src" / "klaude_code"
    package_dir.mkdir(parents=True)
    (package_dir / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "src/klaude_code/mod.py")
    _git(repo, "commit", "-m", "init")
    return repo


class TestCodeFingerprint:
    def test_clean_checkout_uses_head_hash(self, git_repo: Path):
        fingerprint = update._compute_git_fingerprint(str(git_repo))
        assert fingerprint is not None
        assert fingerprint.startswith("git:")
        assert "+" not in fingerprint

    def test_dirty_file_changes_fingerprint(self, git_repo: Path):
        clean = update._compute_git_fingerprint(str(git_repo))
        (git_repo / "src" / "klaude_code" / "mod.py").write_text("x = 1\n# tweak\n", encoding="utf-8")
        dirty = update._compute_git_fingerprint(str(git_repo))
        assert dirty is not None and dirty != clean
        assert "+" in dirty

    def test_untracked_file_changes_fingerprint(self, git_repo: Path):
        clean = update._compute_git_fingerprint(str(git_repo))
        (git_repo / "src" / "klaude_code" / "new.py").write_text("y = 2\n", encoding="utf-8")
        assert update._compute_git_fingerprint(str(git_repo)) != clean

    def test_same_size_same_mtime_content_changes_fingerprint(self, git_repo: Path):
        path = git_repo / "src" / "klaude_code" / "mod.py"
        path.write_text("x = 2\n", encoding="utf-8")
        fixed_mtime = path.stat().st_mtime_ns
        before = update._compute_git_fingerprint(str(git_repo))
        path.write_text("x = 3\n", encoding="utf-8")
        os.utime(path, ns=(fixed_mtime, fixed_mtime))
        after = update._compute_git_fingerprint(str(git_repo))
        assert before is not None and after is not None and after != before

    def test_deleted_and_renamed_paths_are_fingerprinted(self, git_repo: Path):
        (git_repo / "src" / "klaude_code" / "mod.py").unlink()
        deleted = update._compute_git_fingerprint(str(git_repo))
        assert deleted is not None and "+" in deleted

        _git(git_repo, "restore", "src/klaude_code/mod.py")
        _git(git_repo, "mv", "src/klaude_code/mod.py", "src/klaude_code/renamed.py")
        renamed = update._compute_git_fingerprint(str(git_repo))
        assert renamed is not None and renamed != deleted
        (git_repo / "src" / "klaude_code" / "renamed.py").write_text("x = 2\n", encoding="utf-8")
        assert update._compute_git_fingerprint(str(git_repo)) != renamed

    def test_symlink_target_changes_fingerprint(self, git_repo: Path):
        package_dir = git_repo / "src" / "klaude_code"
        (package_dir / "one.py").write_text("1\n", encoding="utf-8")
        (package_dir / "two.py").write_text("2\n", encoding="utf-8")
        link = package_dir / "current.py"
        link.symlink_to("one.py")
        before = update._compute_git_fingerprint(str(git_repo))
        link.unlink()
        link.symlink_to("two.py")
        after = update._compute_git_fingerprint(str(git_repo))
        assert before is not None and after is not None and after != before

    def test_unreadable_dirty_file_is_fingerprinted(self, git_repo: Path, monkeypatch: pytest.MonkeyPatch):
        path = git_repo / "src" / "klaude_code" / "mod.py"
        path.write_text("x = 2\n", encoding="utf-8")
        readable = update._compute_git_fingerprint(str(git_repo))
        original_open = Path.open

        def deny_open(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self == path and args == ("rb",):
                raise PermissionError(13, "denied", str(path))
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_open)
        unreadable = update._compute_git_fingerprint(str(git_repo))
        assert readable is not None and unreadable is not None and unreadable != readable

    def test_new_commit_changes_fingerprint(self, git_repo: Path):
        before = update._compute_git_fingerprint(str(git_repo))
        (git_repo / "src" / "klaude_code" / "mod.py").write_text("x = 2\n", encoding="utf-8")
        _git(git_repo, "commit", "-am", "next")
        after = update._compute_git_fingerprint(str(git_repo))
        assert after is not None and after != before
        assert "+" not in after

    def test_non_git_dir_returns_none(self, tmp_path: Path):
        assert update._compute_git_fingerprint(str(tmp_path)) is None

    def test_wheel_install_uses_package_version(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            update,
            "get_installation_info",
            lambda: update.InstallationInfo(version="9.9.9", install_kind=update.INSTALL_KIND_INDEX, source_url=None),
        )
        assert update._compute_code_fingerprint() == "pkg:9.9.9"

    def test_get_code_fingerprint_is_cached_per_process(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(update, "_cached_code_fingerprint", None)
        calls: list[int] = []

        def _fake_compute() -> str:
            calls.append(1)
            return "git:abc"

        monkeypatch.setattr(update, "_compute_code_fingerprint", _fake_compute)
        assert update.get_code_fingerprint() == "git:abc"
        assert update.get_code_fingerprint() == "git:abc"
        assert len(calls) == 1


def _status_body(
    *,
    fingerprint: str | None,
    pid: int = 100,
    running: int = 0,
    waiting_input: int = 0,
    queued: int = 0,
    protocol_version: int | None = PROTOCOL_VERSION,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ok": True,
        "pid": pid,
        "sessions": {"loaded": 0, "running": running, "waiting_input": waiting_input, "queued": queued},
    }
    if fingerprint is not None:
        body["code_fingerprint"] = fingerprint
    if protocol_version is not None:
        body["protocol_version"] = protocol_version
    return body


class _FakeServer:
    """Records requests; simulates the reload -> fresh-code status sequence.

    Reload re-execs in place, so the pid stays the same; only the fingerprint
    changes after the restart.
    """

    def __init__(self, *, reload_status: int = 200, new_fingerprint: str = "git:local") -> None:
        self.requests: list[tuple[str, str]] = []
        self.reload_status = reload_status
        self.new_fingerprint = new_fingerprint
        self.reloaded = False

    def request(self, method: str, path: str, **_kwargs: Any) -> tuple[int, Any]:
        self.requests.append((method, path))
        if method == "POST" and path == "/api/server/reload":
            if self.reload_status == 200:
                self.reloaded = True
            return self.reload_status, {"detail": "busy"} if self.reload_status == 409 else {"ok": True, "pid": 100}
        if method == "GET" and path == "/api/server/status":
            if self.reloaded:
                return 200, _status_body(fingerprint=self.new_fingerprint, pid=100)
            return 200, _status_body(fingerprint="git:stale", pid=100)
        raise AssertionError(f"unexpected request {method} {path}")

    @property
    def reload_count(self) -> int:
        return sum(1 for method, path in self.requests if method == "POST" and path == "/api/server/reload")


@pytest.fixture
def handshake_env(monkeypatch: pytest.MonkeyPatch) -> _FakeServer:
    server = _FakeServer()
    monkeypatch.setattr(uds_client, "_handshake_done", False)
    monkeypatch.setattr(uds_client, "_local_code_fingerprint", lambda: "git:local")
    monkeypatch.setattr(uds_client, "request", server.request)
    monkeypatch.setattr(uds_client, "_RELOAD_WAIT_TIMEOUT", 0.5)
    monkeypatch.setattr(uds_client.time, "sleep", lambda _s: None)
    return server


class TestVersionHandshake:
    def test_match_idle_no_reload(self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]):
        uds_client.verify_server_code(_status_body(fingerprint="git:local"))
        assert handshake_env.reload_count == 0
        assert capsys.readouterr().err == ""

    def test_match_busy_no_reload(self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]):
        uds_client.verify_server_code(_status_body(fingerprint="git:local", running=2))
        assert handshake_env.reload_count == 0
        assert capsys.readouterr().err == ""

    def test_mismatch_idle_reloads_and_waits(self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]):
        uds_client.verify_server_code(_status_body(fingerprint="git:stale"))
        assert handshake_env.reload_count == 1
        # Waited until the restarted server answered with matching code.
        assert ("GET", "/api/server/status") in handshake_env.requests
        assert capsys.readouterr().err == ""

    def test_mismatch_running_warns_without_reload(
        self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]
    ):
        uds_client.verify_server_code(_status_body(fingerprint="git:stale", running=1))
        assert handshake_env.reload_count == 0
        assert "stale code" in capsys.readouterr().err

    def test_mismatch_waiting_input_warns_without_reload(
        self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]
    ):
        uds_client.verify_server_code(_status_body(fingerprint="git:stale", waiting_input=1))
        assert handshake_env.reload_count == 0
        assert "stale code" in capsys.readouterr().err

    def test_mismatch_queued_warns_without_reload(self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]):
        uds_client.verify_server_code(_status_body(fingerprint="git:stale", queued=3))
        assert handshake_env.reload_count == 0
        assert "stale code" in capsys.readouterr().err

    def test_missing_fingerprint_counts_as_mismatch(self, handshake_env: _FakeServer):
        # A pre-handshake server does not report a fingerprint at all.
        uds_client.verify_server_code(_status_body(fingerprint=None))
        assert handshake_env.reload_count == 1

    def test_protocol_mismatch_idle_reloads(self, handshake_env: _FakeServer):
        uds_client.verify_server_code(_status_body(fingerprint="git:local", protocol_version=PROTOCOL_VERSION + 1))
        assert handshake_env.reload_count == 1

    def test_missing_protocol_busy_warns(self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]):
        uds_client.verify_server_code(_status_body(fingerprint="git:local", protocol_version=None, running=1))
        assert handshake_env.reload_count == 0
        assert "stale code" in capsys.readouterr().err

    def test_reload_conflict_falls_back_to_warning(
        self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]
    ):
        handshake_env.reload_status = 409
        uds_client.verify_server_code(_status_body(fingerprint="git:stale"))
        assert "stale code" in capsys.readouterr().err

    def test_still_stale_after_reload_warns(self, handshake_env: _FakeServer, capsys: pytest.CaptureFixture[str]):
        # The restarted server never reaches the client fingerprint: warn
        # after the wait timeout instead of blocking the command.
        handshake_env.new_fingerprint = "git:other"
        uds_client.verify_server_code(_status_body(fingerprint="git:stale"))
        assert "did not come back on current code" in capsys.readouterr().err

    def test_handshake_runs_once_per_process(self, handshake_env: _FakeServer):
        uds_client.verify_server_code(_status_body(fingerprint="git:stale"))
        assert handshake_env.reload_count == 1
        uds_client.verify_server_code(_status_body(fingerprint="git:stale"))
        assert handshake_env.reload_count == 1
