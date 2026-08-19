"""Skill module - independent skill management system.

This module provides the core skill functionality:
- Skill discovery and loading from multiple directories
- System skill installation
- Per-work_dir skill access via manager functions

Public API (all take the project work_dir; loaders are cached per directory):
- get_skill(name, work_dir) - Get a skill by name
- get_available_skills(work_dir) - Get list of (name, description, location) tuples
- get_skill_loader(work_dir) - Get the SkillLoader for a project directory
- list_skill_names(work_dir) - Get list of skill names
- Skill - Skill data class
- SkillLoader - Skill loader class
"""

from klaude_code.skill.loader import Skill, SkillLoader
from klaude_code.skill.manager import (
    get_available_skills,
    get_skill,
    get_skill_loader,
    list_skill_names,
)

__all__ = [
    "Skill",
    "SkillLoader",
    "get_available_skills",
    "get_skill",
    "get_skill_loader",
    "list_skill_names",
]
