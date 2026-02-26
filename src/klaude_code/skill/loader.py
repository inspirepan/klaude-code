import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from xml.sax.saxutils import escape

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
        Path("~/.agents/skills"),
        Path("~/.config/agents/skills"),
    ]
    # Project-level skills directories (checked in order, later ones override earlier ones with same name)
    PROJECT_SKILLS_DIRS: ClassVar[list[Path]] = [
        Path("./.claude/skills"),
        Path("./.agents/skills"),
    ]

    def __init__(self) -> None:
        """Initialize the skill loader"""
        self.loaded_skills: dict[str, Skill] = {}
        self.skill_warnings_by_location: dict[str, list[str]] = {"system": [], "user": [], "project": []}

    def _iter_skill_files(self, root_dir: Path) -> list[Path]:
        skill_files: list[Path] = []
        visited_dirs: set[Path] = set()

        for dirpath, dirnames, filenames in os.walk(root_dir, topdown=True, followlinks=True):
            current_dir = Path(dirpath)
            try:
                current_real = current_dir.resolve()
            except OSError:
                dirnames[:] = []
                continue

            if current_real in visited_dirs:
                dirnames[:] = []
                continue
            visited_dirs.add(current_real)

            kept_dirnames: list[str] = []
            for dirname in dirnames:
                child_dir = current_dir / dirname
                try:
                    child_real = child_dir.resolve()
                except OSError:
                    continue
                if child_real in visited_dirs:
                    continue
                kept_dirnames.append(dirname)
            dirnames[:] = kept_dirnames

            if "SKILL.md" in filenames:
                skill_files.append(current_dir / "SKILL.md")

        return skill_files

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
            name_val = frontmatter.get("name")
            description = str(frontmatter.get("description", ""))
            parent_dir_name = skill_path.parent.name
            name = str(name_val).strip() if name_val is not None else ""
            if not name:
                name = parent_dir_name

            if not description:
                return None

            if name != parent_dir_name:
                warning = f'{skill_path}: name "{name}" does not match parent directory "{parent_dir_name}"'
                self.skill_warnings_by_location.setdefault(location, []).append(warning)

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
        2. User skills (~/.claude/skills/, ~/.klaude/skills/, ~/.agents/skills/, ~/.config/agents/skills/) - user-level
        3. Project skills (./.claude/skills/, ./.agents/skills/) - project-level, highest priority

        Returns:
            List of successfully loaded Skill objects
        """
        skills: list[Skill] = []
        priority = {"system": 0, "user": 1, "project": 2}
        self.skill_warnings_by_location = {"system": [], "user": [], "project": []}

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
            for skill_file in self._iter_skill_files(system_dir):
                skill = self.load_skill(skill_file, location="system")
                if skill:
                    skills.append(skill)
                    register(skill)

        # Load user-level skills (override system skills if same name)
        for user_dir in self.USER_SKILLS_DIRS:
            expanded_dir = user_dir.expanduser()
            if expanded_dir.exists():
                for skill_file in self._iter_skill_files(expanded_dir):
                    # Skip files under .system directory (already loaded above)
                    if ".system" in skill_file.parts:
                        continue
                    skill = self.load_skill(skill_file, location="user")
                    if skill:
                        skills.append(skill)
                        register(skill)

        # Load project-level skills (override user skills if same name)
        for project_dir in self.PROJECT_SKILLS_DIRS:
            resolved_dir = project_dir.resolve()
            if resolved_dir.exists():
                for skill_file in self._iter_skill_files(resolved_dir):
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

    def get_skills_xml(self) -> str:
        """Generate skill metadata in XML-like format for system prompt.

        Returns:
            XML-like string with all skill metadata entries.
        """
        xml_parts: list[str] = []
        location_order = {"project": 0, "user": 1, "system": 2}
        for skill in sorted(self.loaded_skills.values(), key=lambda s: location_order.get(s.location, 3)):
            name = escape(skill.name)
            description = escape(skill.description.replace("\n", " ").strip())
            location = escape(str(skill.skill_path))
            xml_parts.append(
                "  <skill>\n"
                f"    <name>{name}</name>\n"
                f"    <description>{description}</description>\n"
                f"    <location>{location}</location>\n"
                "  </skill>"
            )
        return "\n".join(xml_parts)

    def get_skills_yaml(self) -> str:
        """Backward-compatible alias for previous method name.

        Returns XML-like metadata used in the system prompt.
        """
        return self.get_skills_xml()
