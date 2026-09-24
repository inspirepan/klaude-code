"""Non-interactive update check helpers.

This module is intentionally frontend-agnostic so it can be used by both the CLI
and terminal UI without introducing cross-layer imports.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import threading
import time
import tomllib
import urllib.request
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast
from urllib.parse import urlparse

PACKAGE_NAME = "klaude-code"
PYPI_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
CHECK_INTERVAL_SECONDS = 3600  # Check at most once per hour
UPDATE_STATE_FILE = "update_state.json"
AUTO_UPGRADE_DONE_ENV = "KLAUDE_AUTO_UPGRADE_DONE"

INSTALL_KIND_UNKNOWN = "unknown"
INSTALL_KIND_INDEX = "index"
INSTALL_KIND_DIRECT_URL = "direct_url"
INSTALL_KIND_LOCAL = "local"
INSTALL_KIND_EDITABLE = "editable"

# Where "latest" came from. Local git checkouts track the upstream branch
# directly so they pick up commits that were never released to PyPI.
UPDATE_SOURCE_PYPI = "pypi"
UPDATE_SOURCE_GIT = "git"

UPGRADE_BRANCH = "main"
_FINGERPRINT_PATHS = ("src/klaude_code", "pyproject.toml", "uv.lock")


class InstallationInfo(NamedTuple):
    """Current package installation metadata."""

    version: str | None
    install_kind: str
    source_url: str | None


class VersionInfo(NamedTuple):
    """Version check result."""

    installed: str | None
    latest: str | None
    update_available: bool
    install_kind: str = INSTALL_KIND_UNKNOWN
    update_source: str = UPDATE_SOURCE_PYPI


class PersistedUpdateInfo(NamedTuple):
    checked_at: float
    installed: str | None
    latest: str | None
    update_available: bool
    install_kind: str = INSTALL_KIND_UNKNOWN
    update_source: str = UPDATE_SOURCE_PYPI


class StartupUpdateSummary(NamedTuple):
    message: str
    level: Literal["info", "warn"] = "warn"


_cached_installation_info: InstallationInfo | None = None
_background_check_lock = threading.Lock()
_background_check_in_progress = False


def _has_uv() -> bool:
    return shutil.which("uv") is not None


def _get_update_state_path() -> Path:
    return Path.home() / ".klaude" / UPDATE_STATE_FILE


def _classify_install_kind(source_url: str | None, direct_url_data: dict[str, Any] | None) -> str:
    if isinstance(direct_url_data, dict):
        dir_info = direct_url_data.get("dir_info")
        if isinstance(dir_info, dict):
            dir_info_typed = cast(dict[str, Any], dir_info)
            if dir_info_typed.get("editable") is True:
                return INSTALL_KIND_EDITABLE

    if source_url is None:
        return INSTALL_KIND_INDEX
    if source_url.startswith("file://"):
        return INSTALL_KIND_LOCAL
    return INSTALL_KIND_DIRECT_URL


def get_installation_info() -> InstallationInfo:
    """Get current installation metadata for this running package."""
    global _cached_installation_info

    if _cached_installation_info is not None:
        return _cached_installation_info

    try:
        dist = distribution(PACKAGE_NAME)
    except PackageNotFoundError:
        info = InstallationInfo(version=None, install_kind=INSTALL_KIND_UNKNOWN, source_url=None)
        _cached_installation_info = info
        return info

    source_url: str | None = None
    direct_url_data: dict[str, Any] | None = None
    direct_url_text = dist.read_text("direct_url.json")
    if direct_url_text:
        try:
            parsed = json.loads(direct_url_text)
            if isinstance(parsed, dict):
                direct_url_data = cast(dict[str, Any], parsed)
                url = direct_url_data.get("url")
                if isinstance(url, str):
                    source_url = url
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    info = InstallationInfo(
        version=dist.version,
        install_kind=_classify_install_kind(source_url, direct_url_data),
        source_url=source_url,
    )
    _cached_installation_info = info
    return info


def get_display_version() -> str:
    """Get a user-facing version label.

    - normal install: ``2.16.0``
    - editable install: ``2.16.0 (editable)``
    """

    install_info = get_installation_info()
    version = install_info.version or "unknown"
    if install_info.install_kind == INSTALL_KIND_EDITABLE:
        return f"{version} (editable)"
    return version


def get_install_source_path() -> str | None:
    """Return local filesystem path when installed from a local file URL."""

    install_info = get_installation_info()
    source_url = install_info.source_url
    if source_url is None:
        return None

    parsed = urlparse(source_url)
    if parsed.scheme != "file":
        return None

    path = urllib.request.url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc != "localhost":
        return f"//{parsed.netloc}{path}"
    return path


_cached_code_fingerprint: str | None = None


def get_code_fingerprint() -> str:
    """Fingerprint of the code this process runs; used for the client/server handshake.

    - git checkout install (editable/local): HEAD commit, plus a digest of
      dirty paths and their current contents
    - wheel install: package version

    Cached per process: the first call freezes the value, so a long-lived
    server keeps reporting the code it actually loaded at startup.
    """

    global _cached_code_fingerprint
    if _cached_code_fingerprint is None:
        _cached_code_fingerprint = _compute_code_fingerprint()
    return _cached_code_fingerprint


def _compute_code_fingerprint() -> str:
    install_info = get_installation_info()
    if install_info.install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL}:
        source_path = get_install_source_path()
        if source_path is not None:
            fingerprint = _compute_git_fingerprint(source_path)
            if fingerprint is not None:
                return fingerprint
    return f"pkg:{install_info.version or 'unknown'}"


def _compute_git_fingerprint(source_path: str) -> str | None:
    """HEAD hash plus dirty-state digest; None when not a usable git checkout."""

    repo_path = Path(source_path).expanduser()
    if not repo_path.is_dir() or shutil.which("git") is None:
        return None
    repo = str(repo_path)
    head = _git_output(repo, ["rev-parse", "HEAD"])
    if head is None:
        return None
    status = _git_bytes(
        repo,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=all",
            "--",
            *_FINGERPRINT_PATHS,
        ],
    )
    if status is None:
        return None
    if not status:
        return f"git:{head[:12]}"
    hasher = hashlib.sha256()
    records = status.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        hasher.update(record)
        hasher.update(b"\0")
        status_code = record[:2]
        if (b"R" in status_code or b"C" in status_code) and index < len(records):
            hasher.update(records[index])
            hasher.update(b"\0")
            index += 1
        rel_path = os.fsdecode(record[3:])
        _hash_worktree_path(hasher, repo_path / rel_path)
    return f"git:{head[:12]}+{hasher.hexdigest()[:12]}"


def _hash_worktree_path(hasher: Any, path: Path) -> None:
    """Hash one dirty worktree path without following symlinks."""

    try:
        path_stat = path.lstat()
    except OSError as exc:
        hasher.update(f"missing:{exc.errno}\0".encode())
        return
    hasher.update(f"mode:{path_stat.st_mode:o}\0".encode())
    if stat.S_ISLNK(path_stat.st_mode):
        try:
            hasher.update(b"symlink:\0" + os.fsencode(os.readlink(path)) + b"\0")
        except OSError as exc:
            hasher.update(f"unreadable-symlink:{exc.errno}\0".encode())
        return
    if not stat.S_ISREG(path_stat.st_mode):
        hasher.update(b"non-regular\0")
        return
    try:
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                hasher.update(chunk)
    except OSError as exc:
        hasher.update(f"unreadable:{exc.errno}\0".encode())
    hasher.update(b"\0")


def _get_installed_version() -> str | None:
    try:
        result = subprocess.run(
            ["uv", "tool", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        for line in result.stdout.splitlines():
            if line.startswith(PACKAGE_NAME):
                parts = line.split()
                if len(parts) >= 2:
                    ver = parts[1]
                    if ver.startswith("v"):
                        ver = ver[1:]
                    return ver
        return None
    except (OSError, subprocess.SubprocessError):
        return None


def _get_latest_version() -> str | None:
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data.get("info", {}).get("version")
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in v.split("."):
        digits = ""
        for c in part:
            if c.isdigit():
                digits += c
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _compare_versions(installed: str, latest: str) -> bool:
    try:
        installed_tuple = _parse_version(installed)
        latest_tuple = _parse_version(latest)
        return latest_tuple > installed_tuple
    except ValueError:
        return False


GIT_QUERY_TIMEOUT = 15
GIT_FETCH_TIMEOUT = 60


def _run_git(
    repo: str,
    args: list[str],
    timeout: int,
    *,
    text: bool = True,
) -> subprocess.CompletedProcess[Any] | None:
    """Run a git command inside ``repo``; return None when git is unusable."""

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True,
            text=text,
            check=False,
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git_output(repo: str, args: list[str], timeout: int = GIT_QUERY_TIMEOUT) -> str | None:
    result = _run_git(repo, args, timeout)
    if result is None or result.returncode != 0 or not isinstance(result.stdout, str):
        return None
    return result.stdout.strip()


def _git_bytes(repo: str, args: list[str], timeout: int = GIT_QUERY_TIMEOUT) -> bytes | None:
    result = _run_git(repo, args, timeout, text=False)
    if result is None or result.returncode != 0 or not isinstance(result.stdout, bytes):
        return None
    return result.stdout


def _fetch_git_version_info(install_info: InstallationInfo, source_path: str) -> VersionInfo | None:
    """Compare the local checkout against ``origin/main``.

    Returns None only when the source path is not a usable git clone.
    """

    repo_path = Path(source_path).expanduser()
    if not repo_path.is_dir() or shutil.which("git") is None:
        return None

    repo = str(repo_path)
    if _git_output(repo, ["rev-parse", "--git-dir"]) is None:
        return None

    remote_ref = f"origin/{UPGRADE_BRANCH}"
    fetch = _run_git(
        repo,
        ["fetch", "--quiet", "origin", f"+refs/heads/{UPGRADE_BRANCH}:refs/remotes/origin/{UPGRADE_BRANCH}"],
        GIT_FETCH_TIMEOUT,
    )
    if fetch is None or fetch.returncode != 0:
        raise RuntimeError(f"git fetch origin {UPGRADE_BRANCH} failed at {repo}; update status is unknown")

    latest_sha = _git_output(repo, ["rev-parse", "--short", remote_ref])
    if latest_sha is None:
        raise RuntimeError(f"cannot resolve {remote_ref} at {repo}; update status is unknown")

    head_sha = _git_output(repo, ["rev-parse", "--short", "HEAD"])
    behind_raw = _git_output(repo, ["rev-list", "--count", f"HEAD..{remote_ref}"])
    if behind_raw is None or not behind_raw.isdecimal():
        raise RuntimeError(f"cannot compare HEAD with {remote_ref} at {repo}; update status is unknown")
    behind = int(behind_raw)

    version = install_info.version or "unknown"
    installed = f"{version} ({head_sha})" if head_sha else version

    return VersionInfo(
        installed=installed,
        latest=latest_sha,
        update_available=behind > 0,
        install_kind=install_info.install_kind,
        update_source=UPDATE_SOURCE_GIT,
    )


def _fetch_version_info() -> VersionInfo | None:
    if not _has_uv():
        return None

    install_info = get_installation_info()

    # Local checkouts track git, not PyPI: the user cloned the source precisely
    # so they can run commits that predate a release.
    if install_info.install_kind in {INSTALL_KIND_EDITABLE, INSTALL_KIND_LOCAL}:
        source_path = get_install_source_path()
        if source_path is not None:
            git_info = _fetch_git_version_info(install_info, source_path)
            if git_info is not None:
                return git_info

    installed = install_info.version or _get_installed_version()
    latest = _get_latest_version()

    update_available = False
    if installed and latest:
        update_available = _compare_versions(installed, latest)

    return VersionInfo(
        installed=installed,
        latest=latest,
        update_available=update_available,
        install_kind=install_info.install_kind,
        update_source=UPDATE_SOURCE_PYPI,
    )


def check_for_updates_blocking() -> VersionInfo | None:
    """Check for updates synchronously (no caching)."""
    return _fetch_version_info()


def write_persisted_update_info(info: PersistedUpdateInfo) -> None:
    path = _get_update_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": info.checked_at,
        "installed": info.installed,
        "latest": info.latest,
        "update_available": info.update_available,
        "install_kind": info.install_kind,
        "update_source": info.update_source,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_persisted_update_info() -> PersistedUpdateInfo | None:
    path = _get_update_state_path()
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    data: dict[str, object] = payload  # type: ignore[assignment]
    checked_at = data.get("checked_at")
    installed = data.get("installed")
    latest = data.get("latest")
    update_available = data.get("update_available")
    install_kind = data.get("install_kind", INSTALL_KIND_UNKNOWN)
    update_source = data.get("update_source", UPDATE_SOURCE_PYPI)

    if not isinstance(checked_at, (int, float)):
        return None
    if installed is not None and not isinstance(installed, str):
        return None
    if latest is not None and not isinstance(latest, str):
        return None
    if not isinstance(update_available, bool):
        return None
    if not isinstance(install_kind, str):
        install_kind = INSTALL_KIND_UNKNOWN
    if not isinstance(update_source, str):
        update_source = UPDATE_SOURCE_PYPI

    return PersistedUpdateInfo(
        checked_at=float(checked_at),
        installed=installed,
        latest=latest,
        update_available=update_available,
        install_kind=install_kind,
        update_source=update_source,
    )


def persist_current_update_info() -> None:
    global _background_check_in_progress

    try:
        try:
            info = _fetch_version_info()
        except RuntimeError as exc:
            from klaude_code.log import log_debug

            log_debug(f"Update check failed: {exc}")
            return
        if info is None:
            return
        write_persisted_update_info(
            PersistedUpdateInfo(
                checked_at=time.time(),
                installed=info.installed,
                latest=info.latest,
                update_available=info.update_available,
                install_kind=info.install_kind,
                update_source=info.update_source,
            )
        )
    finally:
        with _background_check_lock:
            _background_check_in_progress = False


def _start_background_update_check() -> None:
    global _background_check_in_progress

    with _background_check_lock:
        if _background_check_in_progress:
            return
        _background_check_in_progress = True

    thread = threading.Thread(target=persist_current_update_info, daemon=True)
    thread.start()


def has_pending_update() -> bool:
    """True when the last check found newer code or a Git upgrade needs recovery.

    Cheap and file-only: this is the client-side trigger for asking the server
    to upgrade. The server re-validates against its own install metadata.
    """

    info = get_installation_info()
    if info.install_kind in {INSTALL_KIND_LOCAL, INSTALL_KIND_EDITABLE}:
        source_path = get_install_source_path()
        if source_path is not None and _git_upgrade_marker(source_path).exists():
            return True
    persisted = _load_persisted_update_info()
    return persisted is not None and persisted.update_available and bool(persisted.latest)


def perform_upgrade(check: bool = False) -> AutoUpgradeResult:
    """Install the latest code in place; runs inside the server at an idle boundary.

    With ``check`` the upstream is queried first (manual ``klaude upgrade``);
    otherwise the persisted result of the last background check decides. A
    result with ``performed`` False and no message means nothing to install.
    """

    if check:
        try:
            info = check_for_updates_blocking()
        except RuntimeError as exc:
            return AutoUpgradeResult(False, None, f"update check failed: {exc}", "warn")
        if info is None:
            return AutoUpgradeResult(False, None, "update check unavailable: `uv` not found in PATH", "warn")
        write_persisted_update_info(
            PersistedUpdateInfo(
                checked_at=time.time(),
                installed=info.installed,
                latest=info.latest,
                update_available=info.update_available,
                install_kind=info.install_kind,
                update_source=info.update_source,
            )
        )
    return perform_auto_upgrade_if_needed()


def upgraded_code_fingerprint(result: AutoUpgradeResult) -> str | None:
    """Fingerprint of the code just installed, bypassing the per-process cache.

    Git installs are fingerprinted from the checkout that was fast-forwarded;
    wheel installs from the version ``uv`` reported.
    """

    info = get_installation_info()
    if info.install_kind in {INSTALL_KIND_LOCAL, INSTALL_KIND_EDITABLE}:
        source_path = get_install_source_path()
        if source_path is not None:
            fingerprint = _compute_git_fingerprint(source_path)
            if fingerprint is not None:
                return fingerprint
    return f"pkg:{result.new_version}" if result.new_version else None


def _is_persisted_update_info_fresh(info: PersistedUpdateInfo) -> bool:
    return (time.time() - info.checked_at) < CHECK_INTERVAL_SECONDS


def _build_update_message(
    installed: str | None,
    latest: str | None,
    install_kind: str,
    *,
    update_available: bool,
    update_source: str = UPDATE_SOURCE_PYPI,
) -> str | None:
    if not update_available or not latest:
        return None

    installed_display = installed or "unknown"

    if update_source == UPDATE_SOURCE_GIT:
        return (
            f"origin/{UPGRADE_BRANCH} {latest} available. Current {installed_display}; "
            "auto-upgrade applies on next start, or run `klaude upgrade`."
        )

    if install_kind == INSTALL_KIND_EDITABLE:
        return (
            f"PyPI {latest} available. Current {installed_display} (editable install); "
            "run `klaude upgrade` from a clean local checkout."
        )
    if install_kind == INSTALL_KIND_LOCAL:
        return (
            f"PyPI {latest} available. Current {installed_display} (local path install); "
            "run `klaude upgrade` from a clean local checkout."
        )
    if install_kind == INSTALL_KIND_DIRECT_URL:
        return (
            f"PyPI {latest} available. Current {installed_display} (direct URL install); "
            "reinstall from the source URL if needed."
        )
    return f"PyPI {latest} available. Current {installed_display} (PyPI install); run `klaude upgrade`."


def get_startup_update_summary() -> StartupUpdateSummary | None:
    """Return startup welcome update info and trigger a background refresh when needed."""

    persisted = _load_persisted_update_info()
    if persisted is None or not _is_persisted_update_info_fresh(persisted):
        _start_background_update_check()

    info = get_installation_info()
    if info.install_kind in {INSTALL_KIND_LOCAL, INSTALL_KIND_EDITABLE}:
        source_path = get_install_source_path()
        if source_path is not None and _git_upgrade_marker(source_path).exists():
            return StartupUpdateSummary(
                "Local Git upgrade is incomplete; run `klaude upgrade` to retry or inspect its recovery marker",
                level="warn",
            )

    if persisted is None:
        return None
    if persisted.update_source == UPDATE_SOURCE_GIT and not _is_persisted_update_info_fresh(persisted):
        return StartupUpdateSummary("Git update status is stale; checking origin/main again", level="warn")

    message = _build_update_message(
        persisted.installed,
        persisted.latest,
        persisted.install_kind,
        update_available=persisted.update_available,
        update_source=persisted.update_source,
    )
    if message is None:
        return None
    return StartupUpdateSummary(message=message, level="warn")


class AutoUpgradeResult(NamedTuple):
    performed: bool
    new_version: str | None
    message: str | None
    level: Literal["info", "warn"] = "info"
    revision: str | None = None


def _invalidate_persisted_update_info() -> None:
    path = _get_update_state_path()
    if path.exists():
        with contextlib.suppress(OSError):
            path.unlink()


def _git_upgrade_marker(source_path: str) -> Path:
    repo = str(Path(source_path).expanduser().resolve())
    key = hashlib.sha256(os.fsencode(repo)).hexdigest()[:24]
    return Path.home() / ".klaude" / "updates" / f"{key}.json"


def _upgrade_git_install(install_kind: str, source_path: str) -> AutoUpgradeResult:
    """Update a local checkout and its uv tool under a per-checkout process lock."""

    repo = str(Path(source_path).expanduser().resolve())
    if not Path(repo).is_dir() or shutil.which("git") is None or shutil.which("uv") is None:
        return AutoUpgradeResult(False, None, f"Git upgrade unavailable at {repo}: source, git or uv missing", "warn")

    marker = _git_upgrade_marker(repo)
    state_dir = marker.parent
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        lock_file = marker.with_suffix(".lock").open("a+b")
    except OSError as exc:
        return AutoUpgradeResult(False, None, f"Cannot create upgrade lock: {exc}", "warn")

    with lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return AutoUpgradeResult(False, None, "Another upgrade is already running for this checkout", "warn")
        except OSError as exc:
            return AutoUpgradeResult(False, None, f"Cannot lock upgrade: {exc}", "warn")

        stash_sha: str | None = None
        pre_head: str | None = None
        try:
            if marker.exists():
                pending = json.loads(marker.read_text(encoding="utf-8"))
                if pending.get("repo") != repo or not isinstance(pending.get("stash"), (str, type(None))):
                    raise RuntimeError(f"Invalid recovery marker at {marker}; inspect it before retrying")
                if pending.get("phase") == "restore":
                    raise RuntimeError(
                        f"Local changes need manual restoration from stash {pending['stash']}; marker: {marker}"
                    )
                if pending.get("phase") != "install":
                    raise RuntimeError(
                        f"Interrupted stash: inspect git status and git stash list before removing marker {marker}"
                    )
                stash_sha = pending["stash"]
                pre_head = pending.get("pre_head")
                if not isinstance(pre_head, str) or not pre_head:
                    raise RuntimeError(f"Recovery marker lacks pre-upgrade HEAD: {marker}")
                if (
                    _git_output(repo, ["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=all"])
                    != ""
                ):
                    raise RuntimeError(f"Checkout changed since interrupted upgrade; inspect it and marker {marker}")
            else:
                branch = _git_output(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"])
                if branch != UPGRADE_BRANCH:
                    raise RuntimeError(
                        f"Checkout is on {branch or 'detached HEAD'}, not {UPGRADE_BRANCH}; switch manually"
                    )
                status = _git_output(
                    repo, ["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=all"]
                )
                if status is None:
                    raise RuntimeError("Cannot read git status")
                pre_head = _git_output(repo, ["rev-parse", "HEAD"])
                if pre_head is None:
                    raise RuntimeError("Cannot resolve checkout HEAD")
                if status:
                    marker.write_text(
                        json.dumps({"repo": repo, "stash": None, "phase": "stashing", "pre_head": pre_head}),
                        encoding="utf-8",
                    )
                    before = _git_output(repo, ["rev-parse", "--verify", "refs/stash"])
                    stash = _run_git(
                        repo,
                        ["stash", "push", "--include-untracked", "-m", "klaude-upgrade-autostash"],
                        AUTO_UPGRADE_GIT_PULL_TIMEOUT,
                    )
                    after = _git_output(repo, ["rev-parse", "--verify", "refs/stash"])
                    if after is not None and after != before:
                        stash_sha = after
                    if stash is None or stash.returncode != 0 or not stash_sha:
                        raise RuntimeError(
                            f"Stash failed; do not update. Check git stash list (new entry: {stash_sha}); marker: {marker}"
                        )
                    if (
                        _git_output(repo, ["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=all"])
                        != ""
                    ):
                        raise RuntimeError(
                            f"Stash did not clean checkout; changes saved as {stash_sha}; restore manually"
                        )
                # Arm recovery before changing HEAD. Never reset the user's checkout automatically.
                marker.write_text(
                    json.dumps({"repo": repo, "stash": stash_sha, "phase": "install", "pre_head": pre_head}),
                    encoding="utf-8",
                )

            if _git_output(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"]) != UPGRADE_BRANCH:
                raise RuntimeError(f"Checkout branch changed; recovery marker: {marker}")
            if _git_output(repo, ["rev-parse", "HEAD"]) == pre_head:
                fetch = _run_git(
                    repo,
                    ["fetch", "origin", f"+refs/heads/{UPGRADE_BRANCH}:refs/remotes/origin/{UPGRADE_BRANCH}"],
                    GIT_FETCH_TIMEOUT,
                )
                if fetch is None or fetch.returncode != 0:
                    raise RuntimeError("Git fetch failed; no cached origin/main was used")
                merge = _run_git(
                    repo, ["merge", "--ff-only", f"origin/{UPGRADE_BRANCH}"], AUTO_UPGRADE_GIT_PULL_TIMEOUT
                )
                if merge is None or merge.returncode != 0:
                    raise RuntimeError("Git fast-forward failed; checkout was not reset")
            submodule = _run_git(repo, ["submodule", "update", "--init", "--recursive"], AUTO_UPGRADE_SUBMODULE_TIMEOUT)
            if submodule is None or submodule.returncode != 0:
                raise RuntimeError("Git submodule update failed")

            install_args = ["uv", "tool", "install", "--force"]
            if install_kind == INSTALL_KIND_EDITABLE:
                install_args.append("--editable")
            install = subprocess.run(
                [*install_args, repo],
                capture_output=True,
                text=True,
                check=False,
                timeout=AUTO_UPGRADE_UV_INSTALL_TIMEOUT,
            )
            if install.returncode != 0:
                raise RuntimeError(f"uv reinstall failed (exit {install.returncode})")

            expected = tomllib.loads((Path(repo) / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
            tool_dir = subprocess.run(["uv", "tool", "dir"], capture_output=True, text=True, check=False, timeout=10)
            if tool_dir.returncode != 0 or not tool_dir.stdout.strip():
                raise RuntimeError("Cannot locate uv tool environment for verification")
            tool_root = Path(tool_dir.stdout.strip()) / PACKAGE_NAME
            python = tool_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            entry = tool_root / ("Scripts/klaude.exe" if os.name == "nt" else "bin/klaude")
            if not entry.is_file():
                raise RuntimeError(f"Installed klaude entry point missing: {entry}")
            entry_probe = subprocess.run(
                [str(entry), "--version"], capture_output=True, text=True, check=False, timeout=15
            )
            if entry_probe.returncode != 0 or f"{PACKAGE_NAME} {expected}" not in entry_probe.stdout:
                raise RuntimeError(f"Installed klaude entry point failed version check: {entry_probe.stderr[-500:]}")
            probe = subprocess.run(
                [
                    str(python),
                    "-c",
                    "import importlib.metadata as m; import klaude_code; import klaude_code.cli.main; "
                    "import json; d=m.distribution('klaude-code'); "
                    "print(json.dumps({'version': d.version, 'url': json.loads(d.read_text('direct_url.json') or '{}').get('url'), "
                    "'module': klaude_code.__file__, "
                    "'entry': [e.value for e in d.entry_points if e.group == 'console_scripts' and e.name == 'klaude']}))",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if probe.returncode != 0:
                raise RuntimeError(f"Installed klaude cannot import (exit {probe.returncode}): {probe.stderr[-500:]}")
            metadata = json.loads(probe.stdout)
            from urllib.parse import unquote, urlparse

            url = metadata.get("url")
            installed_path = str(Path(unquote(urlparse(url).path)).resolve()) if isinstance(url, str) else None
            if (
                metadata.get("version") != expected
                or installed_path != repo
                or metadata.get("entry") != ["klaude_code.cli.main:app"]
            ):
                raise RuntimeError(f"Installed package metadata does not match source {repo}: {metadata}")
            module_file = metadata.get("module")
            if not isinstance(module_file, str) or not Path(module_file).is_file():
                raise RuntimeError("Installed package module path is unavailable")
            source_code = Path(repo) / "src" / "klaude_code"
            installed_code = Path(module_file).resolve().parent
            if installed_code != source_code.resolve():
                for source_file in source_code.rglob("*.py"):
                    installed_file = installed_code / source_file.relative_to(source_code)
                    if not installed_file.is_file() or source_file.read_bytes() != installed_file.read_bytes():
                        raise RuntimeError(f"Installed code differs from updated source: {source_file}")

            if stash_sha:
                marker.write_text(json.dumps({"repo": repo, "stash": stash_sha, "phase": "restore"}), encoding="utf-8")
                applied = _run_git(repo, ["stash", "apply", "--index", stash_sha], AUTO_UPGRADE_GIT_PULL_TIMEOUT)
                if applied is None or applied.returncode != 0:
                    raise RuntimeError(
                        f"Stash apply conflicted; stash {stash_sha} is preserved. Resolve manually; marker: {marker}"
                    )
                listing = _git_output(repo, ["stash", "list", "--format=%gd %H"])
                selector = next(
                    (
                        line.split()[0]
                        for line in (listing or "").splitlines()
                        if len(line.split()) == 2 and line.split()[1] == stash_sha
                    ),
                    None,
                )
                drop = _run_git(repo, ["stash", "drop", selector], GIT_QUERY_TIMEOUT) if selector else None
                if drop is None or drop.returncode != 0:
                    raise RuntimeError(
                        f"Changes restored but stash {stash_sha} remains; inspect before retrying; marker: {marker}"
                    )
            revision = _git_output(repo, ["rev-parse", "--short=8", "HEAD"])
            if revision is None:
                raise RuntimeError("Cannot verify updated checkout HEAD")
            marker.unlink()
            _invalidate_persisted_update_info()
            return AutoUpgradeResult(
                True, expected, "Git checkout and installed klaude verified; restart the CLI", revision=revision
            )
        except (OSError, ValueError, KeyError, subprocess.SubprocessError, RuntimeError) as exc:
            return AutoUpgradeResult(False, None, f"Git upgrade incomplete: {exc}; retry `klaude upgrade`", "warn")


AUTO_UPGRADE_PYPI_TIMEOUT = 180  # uv tool upgrade, includes solve+download
AUTO_UPGRADE_GIT_STATUS_TIMEOUT = 15
AUTO_UPGRADE_GIT_PULL_TIMEOUT = 60
AUTO_UPGRADE_SUBMODULE_TIMEOUT = 180
AUTO_UPGRADE_UV_INSTALL_TIMEOUT = 180


def _auto_upgrade_pypi() -> AutoUpgradeResult:
    if shutil.which("uv") is None:
        return AutoUpgradeResult(False, None, "auto-upgrade skipped: `uv` not found in PATH", "warn")
    try:
        result = subprocess.run(
            ["uv", "tool", "upgrade", PACKAGE_NAME],
            capture_output=True,
            text=True,
            check=False,
            timeout=AUTO_UPGRADE_PYPI_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return AutoUpgradeResult(
            False, None, f"auto-upgrade skipped: `uv tool upgrade` timed out after {AUTO_UPGRADE_PYPI_TIMEOUT}s", "warn"
        )
    except OSError as err:
        return AutoUpgradeResult(False, None, f"auto-upgrade failed: {err}", "warn")
    if result.returncode != 0:
        return AutoUpgradeResult(False, None, f"auto-upgrade failed (uv tool upgrade exit {result.returncode})", "warn")
    return AutoUpgradeResult(True, _get_installed_version(), None)


def _auto_upgrade_local_git(install_kind: str, source_path: str) -> AutoUpgradeResult:
    return _upgrade_git_install(install_kind, source_path)


def perform_auto_upgrade_if_needed() -> AutoUpgradeResult:
    """Attempt to upgrade the current installation in place.

    The caller should re-exec the process when ``performed`` is True.
    """

    # Prevent recursion after we re-exec post-upgrade.
    if os.environ.get(AUTO_UPGRADE_DONE_ENV) == "1":
        return AutoUpgradeResult(False, None, None)

    # Resolve install metadata from the current process, not the cache, so an
    # out-of-band install-method change does not steer us to the wrong branch.
    install_info = get_installation_info()
    install_kind = install_info.install_kind
    is_local_kind = install_kind in {INSTALL_KIND_LOCAL, INSTALL_KIND_EDITABLE}
    source_path = get_install_source_path() if is_local_kind else None
    persisted = _load_persisted_update_info()
    recovering = source_path is not None and _git_upgrade_marker(source_path).exists()
    if (persisted is None or not persisted.update_available or not persisted.latest) and not recovering:
        return AutoUpgradeResult(False, None, None)

    if recovering:
        pass
    elif persisted is not None and persisted.update_source == UPDATE_SOURCE_GIT:
        # `latest` is a commit sha here, so there is no version ordering to
        # check; the recorded behind-count already answered the question.
        if not is_local_kind:
            # Install method changed out of band; let the next check re-resolve.
            _invalidate_persisted_update_info()
            return AutoUpgradeResult(False, None, None)
    else:
        assert persisted is not None
        assert persisted.latest is not None
        current_version = install_info.version
        if current_version and not _compare_versions(current_version, persisted.latest):
            return AutoUpgradeResult(False, None, None)

    if recovering and source_path is not None:
        result = _auto_upgrade_local_git(install_kind, source_path)
    elif install_kind == INSTALL_KIND_INDEX:
        result = _auto_upgrade_pypi()
    elif is_local_kind:
        if source_path is None:
            return AutoUpgradeResult(False, None, "auto-upgrade skipped: local install source path unavailable", "warn")
        result = _auto_upgrade_local_git(install_kind, source_path)
    else:
        # direct_url or unknown: no safe automatic path
        return AutoUpgradeResult(False, None, None)

    if result.performed:
        _invalidate_persisted_update_info()
        target = (
            f"local Git {result.new_version}"
            if recovering or (persisted is not None and persisted.update_source == UPDATE_SOURCE_GIT)
            else result.new_version or "latest release"
        )
        return AutoUpgradeResult(
            True,
            result.new_version,
            f"Auto-upgraded klaude-code to {target}.",
            "info",
            result.revision,
        )
    return result
