import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Skill:
    """Skill data structure"""

    name: str  # Skill identifier (lowercase-hyphen)
    description: str  # What the skill does and when to use it
    content: str  # Full markdown instructions
    location: str  # Skill location: 'user' or 'project'
    license: str | None = None
    allowed_tools: list[str] | None = None
    metadata: dict[str, str] | None = None
    skill_path: Path | None = None

    def to_prompt(self) -> str:
        """Convert skill to prompt format for agent consumption"""
        return f"""# Skill: {self.name}

{self.description}

---

{self.content}
"""


class SkillLoader:
    """Load and manage Claude Skills from SKILL.md files"""

    def __init__(self, user_skills_dir: str | Path | None = None, project_skills_dir: str | Path | None = None):
        """Initialize with skills directory paths

        Args:
            user_skills_dir: User-level skills directory (e.g., ~/.claude/skills)
            project_skills_dir: Project-level skills directory (e.g., ./.claude/skills)
        """
        self.user_skills_dir = Path(user_skills_dir).expanduser() if user_skills_dir else None
        self.project_skills_dir = Path(project_skills_dir) if project_skills_dir else None
        self.loaded_skills: dict[str, Skill] = {}

    def load_skill(self, skill_path: Path, location: str) -> Skill | None:
        """Load single skill from SKILL.md file

        Args:
            skill_path: Path to SKILL.md file
            location: Skill location ('user' or 'project')

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

        except Exception:
            return None

    def discover_skills(self) -> list[Skill]:
        """Recursively find all SKILL.md files and load them from both user and project directories

        Returns:
            List of successfully loaded Skill objects
        """
        skills: list[Skill] = []

        # Load user-level skills
        if self.user_skills_dir and self.user_skills_dir.exists():
            for skill_file in self.user_skills_dir.rglob("SKILL.md"):
                skill = self.load_skill(skill_file, location="user")
                if skill:
                    skills.append(skill)
                    self.loaded_skills[skill.name] = skill

        # Load project-level skills (override user skills if same name)
        if self.project_skills_dir and self.project_skills_dir.exists():
            for skill_file in self.project_skills_dir.rglob("SKILL.md"):
                skill = self.load_skill(skill_file, location="project")
                if skill:
                    skills.append(skill)
                    self.loaded_skills[skill.name] = skill  # Project skills override user skills

        return skills

    def get_skill(self, name: str) -> Skill | None:
        """Get loaded skill by name

        Args:
            name: Skill name (supports both 'skill-name' and 'namespace:skill-name')

        Returns:
            Skill object or None if not found
        """
        # Support both formats: 'pdf' and 'document-skills:pdf'
        if ":" in name:
            name = name.split(":")[-1]

        return self.loaded_skills.get(name)

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
        # e.g., "[Guide](./docs/guide.md)" -> "[Guide](`/abs/path/to/docs/guide.md`) (use read_file to access)"
        link_pattern = r"\[([^\]]+)\]\((\./)?([^\)]+\.md)\)"

        def replace_link(match: re.Match[str]) -> str:
            text = match.group(1)
            filename = match.group(3)
            abs_path = skill_dir / filename
            return f"[{text}](`{abs_path}`) (use read_file to access)"

        content = re.sub(link_pattern, replace_link, content)

        # Pattern 3: Standalone markdown references
        # e.g., "see reference.md" -> "see `/abs/path/to/reference.md` (use read_file to access)"
        standalone_pattern = r"(?<!\])\b(\w+\.md)\b(?!\))"

        def replace_standalone(match: re.Match[str]) -> str:
            filename = match.group(1)
            abs_path = skill_dir / filename
            return f"`{abs_path}` (use read_file to access)"

        content = re.sub(standalone_pattern, replace_standalone, content)

        return content
