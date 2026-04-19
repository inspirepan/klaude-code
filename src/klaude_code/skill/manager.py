"""Global skill manager with lazy initialization.

This module provides a centralized interface for accessing skills throughout the application.
Skills are loaded lazily on first access to avoid unnecessary IO at startup.
"""

from pathlib import Path

from klaude_code.skill.loader import Skill, SkillLoader
from klaude_code.skill.system_skills import install_system_skills

_loader: SkillLoader | None = None
_initialized: bool = False


def _ensure_initialized() -> SkillLoader:
    """Ensure the skill system is initialized and return the loader.

    The global singleton is bound to the process CWD at first initialization.
    Web mode bypasses this via ``get_available_skills_for_work_dir()``.
    """
    global _loader, _initialized
    if not _initialized:
        install_system_skills()
        _loader = SkillLoader()
        _loader.discover_skills(work_dir=Path.cwd())
        _initialized = True
    assert _loader is not None
    return _loader


def get_skill_loader() -> SkillLoader:
    """Get the global skill loader instance.

    Lazily initializes the skill system on first call.

    Returns:
        The global SkillLoader instance
    """
    return _ensure_initialized()


def get_skill(name: str) -> Skill | None:
    """Get a skill by name.

    Args:
        name: Skill name (supports both 'skill-name' and 'namespace:skill-name')

    Returns:
        Skill object or None if not found
    """
    return _ensure_initialized().get_skill(name)


def get_available_skills() -> list[tuple[str, str, str]]:
    """Get list of available skills for completion and display.

    Returns:
        List of (name, short_description, location) tuples.
        Uses metadata['short-description'] if available, otherwise falls back to description.
        Skills are ordered by priority: project > user > system.
    """
    loader = _ensure_initialized()
    skills = [(s.name, s.short_description, s.location) for s in loader.loaded_skills.values()]
    location_order = {"project": 0, "user": 1, "system": 2}
    skills.sort(key=lambda x: location_order.get(x[2], 3))
    return skills


def get_available_skills_for_work_dir(work_dir: Path) -> list[tuple[str, str, str]]:
    """Get available skills for a specific project directory.

    Unlike get_available_skills() which uses the global singleton tied to
    the process CWD, this creates a fresh loader that discovers project
    skills relative to *work_dir*. Useful for the web UI where different
    sessions may target different project directories.

    Returns:
        List of (name, short_description, location) tuples ordered by priority.
    """
    install_system_skills()
    loader = SkillLoader()
    loader.discover_skills(work_dir=work_dir)
    skills = [(s.name, s.short_description, s.location) for s in loader.loaded_skills.values()]
    location_order = {"project": 0, "user": 1, "system": 2}
    skills.sort(key=lambda x: location_order.get(x[2], 3))
    return skills


def get_skill_warnings_by_location() -> dict[str, list[str]]:
    """Get skill discovery warnings grouped by location."""
    loader = _ensure_initialized()
    warnings = loader.skill_warnings_by_location
    result = {
        "user": sorted(warnings.get("user", [])),
        "project": sorted(warnings.get("project", [])),
        "system": sorted(warnings.get("system", [])),
    }
    if not result["user"] and not result["project"] and not result["system"]:
        return {}
    return result


def list_skill_names() -> list[str]:
    """Get list of all loaded skill names.

    Returns:
        List of skill names
    """
    return _ensure_initialized().list_skills()
