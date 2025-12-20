import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import yaml

from klaude_code.trace import log_debug


@dataclass
class Skill:
    """Skill data structure"""

    name: str  # Skill identifier (lowercase-hyphen)
    description: str  # What the skill does and when to use it
    content: str  # Full markdown instructions
    location: str  # Skill location: 'system', 'user', or 'project'
    license: str | None = None
    allowed_tools: list[str] | None = None
    metadata: dict[str, str] | None = None
    skill_path: Path | None = None

    @property
    def short_description(self) -> str:
        """Get short description for display in completions.

        Returns metadata['short-description'] if available, otherwise falls back to description.
        """
        if self.metadata and "short-description" in self.metadata:
            return self.metadata["short-description"]
        return self.description

    def to_prompt(self) -> str:
        """Convert skill to prompt format for agent consumption"""
        return f"""# Skill: {self.name}

{self.description}

---

{self.content}
"""


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
            markdown_content = content

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    loaded: object = yaml.safe_load(parts[1])
                    if isinstance(loaded, dict):
                        frontmatter = dict(loaded)  # type: ignore[arg-type]
                    markdown_content = parts[2].strip()

            # Extract skill metadata
            name = str(frontmatter.get("name", ""))
            description = str(frontmatter.get("description", ""))

            if not name or not description:
                return None

            # Process relative paths in content
            skill_dir = skill_path.parent
            processed_content = self._process_skill_paths(markdown_content, skill_dir)

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
                content=processed_content,
                location=location,
                license=str(license_val) if license_val is not None else None,
                allowed_tools=allowed_tools,
                metadata=metadata,
                skill_path=skill_path,
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

        # Load system-level skills first (lowest priority, can be overridden)
        system_dir = self.SYSTEM_SKILLS_DIR.expanduser()
        if system_dir.exists():
            for skill_file in system_dir.rglob("SKILL.md"):
                skill = self.load_skill(skill_file, location="system")
                if skill:
                    skills.append(skill)
                    self.loaded_skills[skill.name] = skill

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
                        self.loaded_skills[skill.name] = skill

        # Load project-level skills (override user skills if same name)
        project_dir = self.PROJECT_SKILLS_DIR.resolve()
        if project_dir.exists():
            for skill_file in project_dir.rglob("SKILL.md"):
                skill = self.load_skill(skill_file, location="project")
                if skill:
                    skills.append(skill)
                    self.loaded_skills[skill.name] = skill

        # Log discovery summary
        if skills:
            system_count = sum(1 for s in skills if s.location == "system")
            user_count = sum(1 for s in skills if s.location == "user")
            project_count = sum(1 for s in skills if s.location == "project")
            parts: list[str] = []
            if system_count > 0:
                parts.append(f"{system_count} system")
            if user_count > 0:
                parts.append(f"{user_count} user")
            if project_count > 0:
                parts.append(f"{project_count} project")
            log_debug(f"Discovered {len(skills)} Claude Skills ({', '.join(parts)})")

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
        """Generate Level 1 metadata in XML format for tool description

        Returns:
            XML string with all skill metadata
        """
        xml_parts: list[str] = []
        for skill in self.loaded_skills.values():
            xml_parts.append(f"""<skill>
<name>{skill.name}</name>
<description>{skill.description}</description>
<location>{skill.location}</location>
</skill>""")
        return "\n".join(xml_parts)

    def _process_skill_paths(self, content: str, skill_dir: Path) -> str:
        """Convert relative paths to absolute paths for Level 3+

        Supports:
        - scripts/, examples/, templates/, reference/ directories
        - Markdown document references
        - Markdown links [text](path)

        Args:
            content: Original skill content
            skill_dir: Directory containing the SKILL.md file

        Returns:
            Content with absolute paths
        """
        # Pattern 1: Directory-based paths (scripts/, examples/, etc.)
        # e.g., "python scripts/generate.py" -> "python /abs/path/to/scripts/generate.py"
        dir_pattern = r"\b(scripts|examples|templates|reference)/([^\s\)]+)"

        def replace_dir_path(match: re.Match[str]) -> str:
            directory = match.group(1)
            filename = match.group(2)
            abs_path = skill_dir / directory / filename
            return str(abs_path)

        content = re.sub(dir_pattern, replace_dir_path, content)

        # Pattern 2: Markdown links [text](./path or path)
        # e.g., "[Guide](./docs/guide.md)" -> "[Guide](`/abs/path/to/docs/guide.md`) (use the Read tool to access)"
        link_pattern = r"\[([^\]]+)\]\((\./)?([^\)]+\.md)\)"

        def replace_link(match: re.Match[str]) -> str:
            text = match.group(1)
            filename = match.group(3)
            abs_path = skill_dir / filename
            return f"[{text}](`{abs_path}`) (use the Read tool to access)"

        content = re.sub(link_pattern, replace_link, content)

        # Pattern 3: Standalone markdown references
        # e.g., "see reference.md" -> "see `/abs/path/to/reference.md` (use the Read tool to access)"
        standalone_pattern = r"(?<!\])\b(\w+\.md)\b(?!\))"

        def replace_standalone(match: re.Match[str]) -> str:
            filename = match.group(1)
            abs_path = skill_dir / filename
            return f"`{abs_path}` (use the Read tool to access)"

        content = re.sub(standalone_pattern, replace_standalone, content)

        return content
