"""Non-interactive update check helpers.

This module is intentionally frontend-agnostic so it can be used by both the CLI
and terminal UI without introducing cross-layer imports.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import threading
import time
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
_background_auto_upgrade_lock = threading.Lock()
_background_auto_upgrade_in_progress = False


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

    Returns None when the source path is not a usable git clone, so the caller
    can fall back to the PyPI comparison.
    """

    repo_path = Path(source_path).expanduser()
    if not repo_path.is_dir() or shutil.which("git") is None:
        return None

    repo = str(repo_path)
    if _git_output(repo, ["rev-parse", "--git-dir"]) is None:
        return None

    remote_ref = f"origin/{UPGRADE_BRANCH}"
    fetch = _run_git(repo, ["fetch", "--quiet", "origin", UPGRADE_BRANCH], GIT_FETCH_TIMEOUT)
    if fetch is None or fetch.returncode != 0:
        # Offline or no `origin`: fall back to whatever was fetched previously.
        pass

    latest_sha = _git_output(repo, ["rev-parse", "--short", remote_ref])
    if latest_sha is None:
        return None

    head_sha = _git_output(repo, ["rev-parse", "--short", "HEAD"])
    behind_raw = _git_output(repo, ["rev-list", "--count", f"HEAD..{remote_ref}"])
    try:
        behind = int(behind_raw) if behind_raw else 0
    except ValueError:
        behind = 0

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
        info = _fetch_version_info()
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


def _run_background_auto_upgrade() -> None:
    global _background_auto_upgrade_in_progress

    try:
        perform_auto_upgrade_if_needed()
    except Exception as exc:
        from klaude_code.log import log_debug

        log_debug(f"Background auto-upgrade failed: {exc}")
    finally:
        with _background_auto_upgrade_lock:
            _background_auto_upgrade_in_progress = False


def start_background_auto_upgrade_if_needed() -> None:
    """Start auto-upgrade work in a background thread.

    Background upgrades apply to the next process start; the current process is
    not re-execed.
    """

    global _background_auto_upgrade_in_progress

    with _background_auto_upgrade_lock:
        if _background_auto_upgrade_in_progress:
            return
        _background_auto_upgrade_in_progress = True

    thread = threading.Thread(target=_run_background_auto_upgrade, name="auto-upgrade", daemon=True)
    thread.start()


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

    if persisted is None:
        return None

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


def _invalidate_persisted_update_info() -> None:
    path = _get_update_state_path()
    if path.exists():
        with contextlib.suppress(OSError):
            path.unlink()


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
    return AutoUpgradeResult(True, None, None)


def _auto_upgrade_local_git(install_kind: str, source_path: str) -> AutoUpgradeResult:
    repo_path = Path(source_path).expanduser()
    if not repo_path.exists() or not repo_path.is_dir():
        return AutoUpgradeResult(
            False, None, f"auto-upgrade skipped: local source path unavailable: {source_path}", "warn"
        )
    if shutil.which("uv") is None:
        return AutoUpgradeResult(False, None, "auto-upgrade skipped: `uv` not found in PATH", "warn")
    if shutil.which("git") is None:
        return AutoUpgradeResult(False, None, "auto-upgrade skipped: `git` not found in PATH", "warn")

    source_display = str(repo_path)
    # `--ignore-submodules=all` keeps a moved submodule pointer from looking
    # like a local edit, which would otherwise wedge auto-upgrade permanently
    # after the first pull that bumps the submodule.
    status = _run_git(
        source_display,
        ["status", "--porcelain", "--ignore-submodules=all"],
        AUTO_UPGRADE_GIT_STATUS_TIMEOUT,
    )
    if status is None:
        return AutoUpgradeResult(False, None, f"auto-upgrade skipped: `git status` failed at {source_display}", "warn")
    if status.returncode != 0:
        return AutoUpgradeResult(False, None, f"auto-upgrade skipped: not a git repo at {source_display}", "warn")
    if status.stdout.strip():
        return AutoUpgradeResult(
            False,
            None,
            f"auto-upgrade skipped: local checkout has uncommitted changes at {source_display}",
            "info",
        )

    # Never move someone off their working branch behind their back; that is
    # the manual `klaude upgrade` path's job.
    branch = _git_output(source_display, ["rev-parse", "--abbrev-ref", "HEAD"])
    if branch != UPGRADE_BRANCH:
        return AutoUpgradeResult(
            False,
            None,
            f"auto-upgrade skipped: local checkout is on `{branch or 'detached HEAD'}`, not `{UPGRADE_BRANCH}`",
            "info",
        )

    pull = _run_git(source_display, ["pull", "--ff-only"], AUTO_UPGRADE_GIT_PULL_TIMEOUT)
    if pull is None or pull.returncode != 0:
        return AutoUpgradeResult(
            False, None, f"auto-upgrade skipped: `git pull --ff-only` failed at {source_display}", "warn"
        )

    submodule = _run_git(
        source_display,
        ["submodule", "update", "--init", "--recursive"],
        AUTO_UPGRADE_SUBMODULE_TIMEOUT,
    )
    if submodule is None or submodule.returncode != 0:
        return AutoUpgradeResult(
            False,
            None,
            f"auto-upgrade failed: `git submodule update` failed at {source_display}",
            "warn",
        )

    install_args = ["uv", "tool", "install", "--force"]
    if install_kind == INSTALL_KIND_EDITABLE:
        install_args.append("--editable")
    install_args.append(source_display)
    try:
        install = subprocess.run(
            install_args, capture_output=True, text=True, check=False, timeout=AUTO_UPGRADE_UV_INSTALL_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return AutoUpgradeResult(
            False,
            None,
            f"auto-upgrade skipped: `uv tool install` timed out after {AUTO_UPGRADE_UV_INSTALL_TIMEOUT}s",
            "warn",
        )
    if install.returncode != 0:
        return AutoUpgradeResult(False, None, f"auto-upgrade failed: reinstall exit {install.returncode}", "warn")
    return AutoUpgradeResult(True, None, None)


def perform_auto_upgrade_if_needed() -> AutoUpgradeResult:
    """Attempt to upgrade the current installation in place.

    The caller should re-exec the process when ``performed`` is True.
    """

    # Prevent recursion after we re-exec post-upgrade.
    if os.environ.get(AUTO_UPGRADE_DONE_ENV) == "1":
        return AutoUpgradeResult(False, None, None)

    persisted = _load_persisted_update_info()
    if persisted is None or not persisted.update_available or not persisted.latest:
        return AutoUpgradeResult(False, None, None)

    # Resolve install metadata from the current process, not the cache, so an
    # out-of-band install-method change does not steer us to the wrong branch.
    install_info = get_installation_info()
    install_kind = install_info.install_kind
    is_local_kind = install_kind in {INSTALL_KIND_LOCAL, INSTALL_KIND_EDITABLE}

    if persisted.update_source == UPDATE_SOURCE_GIT:
        # `latest` is a commit sha here, so there is no version ordering to
        # check; the recorded behind-count already answered the question.
        if not is_local_kind:
            # Install method changed out of band; let the next check re-resolve.
            _invalidate_persisted_update_info()
            return AutoUpgradeResult(False, None, None)
    else:
        current_version = install_info.version
        if current_version and not _compare_versions(current_version, persisted.latest):
            return AutoUpgradeResult(False, None, None)

    if install_kind == INSTALL_KIND_INDEX:
        result = _auto_upgrade_pypi()
    elif is_local_kind:
        source_path = get_install_source_path()
        if source_path is None:
            return AutoUpgradeResult(False, None, "auto-upgrade skipped: local install source path unavailable", "warn")
        result = _auto_upgrade_local_git(install_kind, source_path)
    else:
        # direct_url or unknown: no safe automatic path
        return AutoUpgradeResult(False, None, None)

    if result.performed:
        _invalidate_persisted_update_info()
        if persisted.update_source == UPDATE_SOURCE_GIT:
            target = f"origin/{UPGRADE_BRANCH} {persisted.latest}"
        else:
            target = persisted.latest
        return AutoUpgradeResult(True, persisted.latest, f"Auto-upgraded klaude-code to {target}.", "info")
    return result
