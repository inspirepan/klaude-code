from pathlib import Path

from pydantic import BaseModel

from klaude_code.core.tool.memory.skill_loader import SkillLoader
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools


@register(tools.SKILL)
class SkillTool(ToolABC):
    """Tool to execute/load a skill within the main conversation"""

    _skill_loader: SkillLoader | None = None
    _discovery_done: bool = False

    @classmethod
    def set_skill_loader(cls, loader: SkillLoader) -> None:
        """Set the skill loader instance"""
        cls._skill_loader = loader
        cls._discovery_done = False

    @classmethod
    def _ensure_skills_discovered(cls) -> None:
        if cls._discovery_done:
            return
        if cls._skill_loader is not None:
            cls._skill_loader.discover_skills()
        cls._discovery_done = True

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        """Generate schema with embedded available skills metadata"""
        cls._ensure_skills_discovered()
        skills_xml = cls._generate_skills_xml()

        return llm_param.ToolSchema(
            name=tools.SKILL,
            type="function",
            description=load_desc(Path(__file__).parent / "skill_tool.md", {"skills_xml": skills_xml}),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Name of the skill to execute",
                    }
                },
                "required": ["command"],
            },
        )

    @classmethod
    def _generate_skills_xml(cls) -> str:
        """Generate XML format skills metadata"""
        if not cls._skill_loader:
            return ""

        xml_parts: list[str] = []
        for skill in cls._skill_loader.loaded_skills.values():
            xml_parts.append(f"""<skill>
<name>{skill.name}</name>
<description>{skill.description}</description>
<location>{skill.location}</location>
</skill>""")
        return "\n".join(xml_parts)

    class SkillArguments(BaseModel):
        command: str

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        """Load and return full skill content"""
        try:
            args = cls.SkillArguments.model_validate_json(arguments)
        except ValueError as e:
            return model.ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )

        cls._ensure_skills_discovered()

        if not cls._skill_loader:
            return model.ToolResultItem(
                status="error",
                output="Skill loader not initialized",
            )

        skill = cls._skill_loader.get_skill(args.command)

        if not skill:
            available = ", ".join(cls._skill_loader.list_skills())
            return model.ToolResultItem(
                status="error",
                output=f"Skill '{args.command}' does not exist. Available skills: {available}",
            )

        # Get base directory from skill_path
        base_dir = str(skill.skill_path.parent) if skill.skill_path else "unknown"

        # Return with loading message format
        result = f"""<command-message>The "{skill.name}" skill is running</command-message>
<command-name>{skill.name}</command-name>

Base directory for this skill: {base_dir}

{skill.to_prompt()}"""
        return model.ToolResultItem(status="success", output=result)
