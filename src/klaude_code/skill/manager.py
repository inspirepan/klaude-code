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


def format_available_skills_for_system_prompt() -> str:
    """Format skills metadata for inclusion in the system prompt.

    This follows the progressive-disclosure approach:
    - Keep only name/description + file location in the always-on system prompt
    - Load the full SKILL.md content on demand via the Read tool when needed
    """

    try:
        loader = _ensure_initialized()
        skills_xml_raw = loader.get_skills_xml()
        if not skills_xml_raw.strip():
            return ""
        skills_xml = skills_xml_raw.rstrip()

        return f"""

# Skills

Skills are optional task-specific instructions stored as `SKILL.md` files.

How to use skills:
- Use the metadata in <available_skills> to decide whether a skill applies.
- When the task matches a skill's description, use the `Read` tool to load the `SKILL.md` at the given <location>.
- Treat the skill <base_dir> as the working directory when following SKILL.md instructions (equivalent to running `cd <base_dir>` first).
- Resolve any relative paths in SKILL.md (such as `scripts/...`, `references/...`, `assets/...`) against that <base_dir>.

Important:
- Only use skills listed in <available_skills> below.
- Keep context small: do NOT load skill files unless needed.

The list below is metadata only (name/description/location). The full instructions live in the referenced file.

<available_skills>
{skills_xml}
</available_skills>"""
    except Exception:
        # Skills are an optional enhancement; do not fail prompt construction if discovery breaks.
        return ""
