"""Per-work_dir skill loaders with lazy initialization.

This module provides a centralized interface for accessing skills throughout
the application. One server process hosts sessions rooted in different
directories, so loaders are cached per work_dir instead of a process-wide
singleton bound to the CWD. Skills are loaded lazily on first access to
avoid unnecessary IO at startup.
"""

import threading
from pathlib import Path

from klaude_code.skill.loader import Skill, SkillLoader
from klaude_code.skill.system_skills import install_system_skills

_loaders: dict[Path, SkillLoader] = {}
_loaders_lock = threading.Lock()


def get_skill_loader(work_dir: Path) -> SkillLoader:
    """Get the skill loader for a project directory.

    Lazily discovers skills relative to *work_dir* on first call; the loader
    is cached for the process lifetime (matching the previous singleton's
    no-refresh behavior).
    """
    key = work_dir.resolve()
    with _loaders_lock:
        loader = _loaders.get(key)
        if loader is None:
            install_system_skills()
            loader = SkillLoader()
            loader.discover_skills(work_dir=key)
            _loaders[key] = loader
    return loader


def get_skill(name: str, work_dir: Path) -> Skill | None:
    """Get a skill by name.

    Args:
        name: Skill name (supports both 'skill-name' and 'namespace:skill-name')
        work_dir: Project directory whose skills to search

    Returns:
        Skill object or None if not found
    """
    return get_skill_loader(work_dir).get_skill(name)


def get_available_skills(work_dir: Path) -> list[tuple[str, str, str]]:
    """Get list of available skills for completion and display.

    Returns:
        List of (name, short_description, location) tuples.
        Uses metadata['short-description'] if available, otherwise falls back to description.
        Skills are ordered by priority: project > user > system.
    """
    loader = get_skill_loader(work_dir)
    skills = [(s.name, s.short_description, s.location) for s in loader.loaded_skills.values()]
    location_order = {"project": 0, "user": 1, "system": 2}
    skills.sort(key=lambda x: location_order.get(x[2], 3))
    return skills


def get_skill_warnings_by_location(work_dir: Path) -> dict[str, list[str]]:
    """Get skill discovery warnings grouped by location."""
    loader = get_skill_loader(work_dir)
    warnings = loader.skill_warnings_by_location
    result = {
        "user": sorted(warnings.get("user", [])),
        "project": sorted(warnings.get("project", [])),
        "system": sorted(warnings.get("system", [])),
    }
    if not result["user"] and not result["project"] and not result["system"]:
        return {}
    return result


def list_skill_names(work_dir: Path) -> list[str]:
    """Get list of all loaded skill names.

    Returns:
        List of skill names
    """
    return get_skill_loader(work_dir).list_skills()
