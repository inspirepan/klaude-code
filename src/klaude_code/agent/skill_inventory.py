from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")


def _safe_skill_call(fn: Callable[[], _T], default: _T) -> _T:
    try:
        return fn()
    except Exception:
        return default


def get_skill_names_by_location() -> dict[str, list[str]]:
    """Return available skill names grouped by location.

    The UI should not import the skill system directly. Core can expose a
    lightweight summary suitable for WelcomeEvent rendering.
    """

    try:
        # Import lazily to keep startup overhead minimal and avoid unnecessary
        # coupling at module import time.
        from klaude_code.skill.manager import get_available_skills
    except Exception:
        return {}

    def _collect() -> dict[str, list[str]]:
        result: dict[str, list[str]] = {"user": [], "project": [], "system": []}
        for name, _desc, location in get_available_skills():
            if location == "user":
                result["user"].append(name)
            elif location == "project":
                result["project"].append(name)
            elif location == "system":
                result["system"].append(name)

        if not result["user"] and not result["project"] and not result["system"]:
            return {}

        result["user"].sort()
        result["project"].sort()
        result["system"].sort()
        return result

    return _safe_skill_call(_collect, {})


def get_skill_warnings_by_location() -> dict[str, list[str]]:
    """Return skill discovery warnings grouped by location."""

    try:
        from klaude_code.skill.manager import get_skill_warnings_by_location
    except Exception:
        return {}

    return _safe_skill_call(get_skill_warnings_by_location, {})


def warmup_skill_inventory() -> None:
    """Load the shared skill inventory for later welcome and attachment use."""
    get_skill_names_by_location()
    get_skill_warnings_by_location()
