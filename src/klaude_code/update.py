"""Non-interactive update check helpers.

This module is intentionally frontend-agnostic so it can be used by both the CLI
and terminal UI without introducing cross-layer imports.
"""

from __future__ import annotations

import json
import shutil
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

INSTALL_KIND_UNKNOWN = "unknown"
INSTALL_KIND_INDEX = "index"
INSTALL_KIND_DIRECT_URL = "direct_url"
INSTALL_KIND_LOCAL = "local"
INSTALL_KIND_EDITABLE = "editable"


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


class PersistedUpdateInfo(NamedTuple):
    checked_at: float
    installed: str | None
    latest: str | None
    update_available: bool
    install_kind: str = INSTALL_KIND_UNKNOWN


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


def _fetch_version_info() -> VersionInfo | None:
    if not _has_uv():
        return None

    install_info = get_installation_info()
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

    return PersistedUpdateInfo(
        checked_at=float(checked_at),
        installed=installed,
        latest=latest,
        update_available=update_available,
        install_kind=install_kind,
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


def _is_persisted_update_info_fresh(info: PersistedUpdateInfo) -> bool:
    return (time.time() - info.checked_at) < CHECK_INTERVAL_SECONDS


def _build_update_message(
    installed: str | None, latest: str | None, install_kind: str, *, update_available: bool
) -> str | None:
    if not update_available or not latest:
        return None

    installed_display = installed or "unknown"
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
    )
    if message is None:
        return None
    return StartupUpdateSummary(message=message, level="warn")
