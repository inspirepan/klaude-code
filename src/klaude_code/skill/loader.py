from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import yaml

from klaude_code.log import log_debug


@dataclass
class Skill:
    """Skill data structure"""

    name: str  # Skill identifier (lowercase-hyphen)
    description: str  # What the skill does and when to use it
    location: str  # Skill source: 'system', 'user', or 'project'
    skill_path: Path
    base_dir: Path
    license: str | None = None
    allowed_tools: list[str] | None = None
    metadata: dict[str, str] | None = None

    @property
    def short_description(self) -> str:
        """Get short description for display in completions.

        Returns metadata['short-description'] if available, otherwise falls back to description.
        """
        if self.metadata and "short-description" in self.metadata:
            return self.metadata["short-description"]
        return self.description


class SkillLoader:
    """Load and manage Claude Skills from SKILL.md files"""

    # System-level skills directory (built-in, lowest priority)
    SYSTEM_SKILLS_DIR: ClassVar[Path] = Path("~/.klaude/skills/.system")

    # User-level skills directories (checked in order, later ones override earlier ones with same name)
    USER_SKILLS_DIRS: ClassVar[list[Path]] = [
        Path("~/.claude/skills"),
        Path("~/.klaude/skills"),
    ]
    # Project-level skills directory (highest priority)
    PROJECT_SKILLS_DIR: ClassVar[Path] = Path("./.claude/skills")

    def __init__(self) -> None:
        """Initialize the skill loader"""
        self.loaded_skills: dict[str, Skill] = {}

    def load_skill(self, skill_path: Path, location: str) -> Skill | None:
        """Load single skill from SKILL.md file

        Args:
            skill_path: Path to SKILL.md file
            location: Skill location ('system', 'user', or 'project')

        Returns:
            Skill object or None if loading failed
        """
        if not skill_path.exists():
            return None

        try:
            content = skill_path.read_text(encoding="utf-8")

            # Parse YAML frontmatter
            frontmatter: dict[str, object] = {}

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    loaded: object = yaml.safe_load(parts[1])
                    if isinstance(loaded, dict):
                        frontmatter = dict(loaded)  # type: ignore[arg-type]

            # Extract skill metadata
            name = str(frontmatter.get("name", ""))
            description = str(frontmatter.get("description", ""))

            if not name or not description:
                return None

            # Create Skill object
            license_val = frontmatter.get("license")
            allowed_tools_val = frontmatter.get("allowed-tools")
            metadata_val = frontmatter.get("metadata")

            # Convert allowed_tools
            allowed_tools: list[str] | None = None
            if isinstance(allowed_tools_val, list):
                allowed_tools = [str(t) for t in allowed_tools_val]  # type: ignore[misc]

            # Convert metadata
            metadata: dict[str, str] | None = None
            if isinstance(metadata_val, dict):
                metadata = {str(k): str(v) for k, v in metadata_val.items()}  # type: ignore[misc]

            skill = Skill(
                name=name,
                description=description,
                location=location,
                license=str(license_val) if license_val is not None else None,
                allowed_tools=allowed_tools,
                metadata=metadata,
                skill_path=skill_path.resolve(),
                base_dir=skill_path.parent.resolve(),
            )

            return skill

        except (OSError, yaml.YAMLError) as e:
            log_debug(f"Failed to load skill from {skill_path}: {e}")
            return None

    def discover_skills(self) -> list[Skill]:
        """Recursively find all SKILL.md files and load them from system, user and project directories.

        Loading order (lower priority first, higher priority overrides):
        1. System skills (~/.klaude/skills/.system/) - built-in, lowest priority
        2. User skills (~/.claude/skills/, ~/.klaude/skills/) - user-level
        3. Project skills (./.claude/skills/) - project-level, highest priority

        Returns:
            List of successfully loaded Skill objects
        """
        skills: list[Skill] = []
        priority = {"system": 0, "user": 1, "project": 2}

        def register(skill: Skill) -> None:
            existing = self.loaded_skills.get(skill.name)
            if existing is None:
                self.loaded_skills[skill.name] = skill
                return
            if priority.get(skill.location, -1) >= priority.get(existing.location, -1):
                self.loaded_skills[skill.name] = skill

        # Load system-level skills first (lowest priority, can be overridden)
        system_dir = self.SYSTEM_SKILLS_DIR.expanduser()
        if system_dir.exists():
            for skill_file in system_dir.rglob("SKILL.md"):
                skill = self.load_skill(skill_file, location="system")
                if skill:
                    skills.append(skill)
                    register(skill)

        # Load user-level skills (override system skills if same name)
        for user_dir in self.USER_SKILLS_DIRS:
            expanded_dir = user_dir.expanduser()
            if expanded_dir.exists():
                for skill_file in expanded_dir.rglob("SKILL.md"):
                    # Skip files under .system directory (already loaded above)
                    if ".system" in skill_file.parts:
                        continue
                    skill = self.load_skill(skill_file, location="user")
                    if skill:
                        skills.append(skill)
                        register(skill)

        # Load project-level skills (override user skills if same name)
        project_dir = self.PROJECT_SKILLS_DIR.resolve()
        if project_dir.exists():
            for skill_file in project_dir.rglob("SKILL.md"):
                skill = self.load_skill(skill_file, location="project")
                if skill:
                    skills.append(skill)
                    register(skill)

        # Log discovery summary
        if self.loaded_skills:
            selected = list(self.loaded_skills.values())
            system_count = sum(1 for s in selected if s.location == "system")
            user_count = sum(1 for s in selected if s.location == "user")
            project_count = sum(1 for s in selected if s.location == "project")
            parts: list[str] = []
            if system_count > 0:
                parts.append(f"{system_count} system")
            if user_count > 0:
                parts.append(f"{user_count} user")
            if project_count > 0:
                parts.append(f"{project_count} project")
            log_debug(f"Loaded {len(self.loaded_skills)} Claude Skills ({', '.join(parts)})")

        return skills

    def get_skill(self, name: str) -> Skill | None:
        """Get loaded skill by name

        Args:
            name: Skill name (supports both 'skill-name' and 'namespace:skill-name')

        Returns:
            Skill object or None if not found
        """
        # Prefer exact match first (supports namespaced skill names).
        skill = self.loaded_skills.get(name)
        if skill is not None:
            return skill

        # Support both formats: 'pdf' and 'document-skills:pdf'
        if ":" in name:
            short = name.split(":")[-1]
            return self.loaded_skills.get(short)

        return None

    def list_skills(self) -> list[str]:
        """Get list of all loaded skill names"""
        return list(self.loaded_skills.keys())

    def get_skills_yaml(self) -> str:
        """Generate skill metadata in YAML format for system prompt.

        Returns:
            YAML string with all skill metadata
        """
        yaml_parts: list[str] = []
        location_order = {"project": 0, "user": 1, "system": 2}
        for skill in sorted(self.loaded_skills.values(), key=lambda s: location_order.get(s.location, 3)):
            # Escape description for YAML (handle multi-line and special chars)
            desc = skill.description.replace("\n", " ").strip()
            yaml_parts.append(
                f"- name: {skill.name}\n"
                f"  description: {desc}\n"
                f"  scope: {skill.location}\n"
                f"  location: {skill.skill_path}"
            )
        return "\n".join(yaml_parts)
