from __future__ import annotations


def get_loaded_skill_names_by_location() -> dict[str, list[str]]:
    """Return loaded skill names grouped by location.

    The UI should not import the skill system directly. Core can expose a
    lightweight summary suitable for WelcomeEvent rendering.
    """

    try:
        # Import lazily to keep startup overhead minimal and avoid unnecessary
        # coupling at module import time.
        from klaude_code.skill.manager import get_available_skills
    except Exception:
        return {}

    result: dict[str, list[str]] = {"user": [], "project": [], "system": []}
    try:
        for name, _desc, location in get_available_skills():
            if location == "user":
                result["user"].append(name)
            elif location == "project":
                result["project"].append(name)
            elif location == "system":
                result["system"].append(name)
    except Exception:
        return {}

    if not result["user"] and not result["project"] and not result["system"]:
        return {}

    result["user"].sort()
    result["project"].sort()
    result["system"].sort()
    return result
