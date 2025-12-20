"""Global skill manager with lazy initialization.

This module provides a centralized interface for accessing skills throughout the application.
Skills are loaded lazily on first access to avoid unnecessary IO at startup.
"""

from klaude_code.skill.loader import Skill, SkillLoader
from klaude_code.skill.system_skills import install_system_skills

_loader: SkillLoader | None = None
_initialized: bool = False


def _ensure_initialized() -> SkillLoader:
    """Ensure the skill system is initialized and return the loader."""
    global _loader, _initialized
    if not _initialized:
        install_system_skills()
        _loader = SkillLoader()
        _loader.discover_skills()
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


def list_skill_names() -> list[str]:
    """Get list of all loaded skill names.

    Returns:
        List of skill names
    """
    return _ensure_initialized().list_skills()
