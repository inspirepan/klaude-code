"""Skill module - independent skill management system.

This module provides the core skill functionality:
- Skill discovery and loading from multiple directories
- System skill installation
- Global skill access via manager functions

Public API:
- get_skill(name) - Get a skill by name
- get_available_skills() - Get list of (name, description, location) tuples
- get_skill_loader() - Get the global SkillLoader instance
- list_skill_names() - Get list of skill names
- Skill - Skill data class
- SkillLoader - Skill loader class
"""

from klaude_code.skill.loader import Skill, SkillLoader
from klaude_code.skill.manager import get_available_skills, get_skill, get_skill_loader, list_skill_names

__all__ = [
    "Skill",
    "SkillLoader",
    "get_available_skills",
    "get_skill",
    "get_skill_loader",
    "list_skill_names",
]
