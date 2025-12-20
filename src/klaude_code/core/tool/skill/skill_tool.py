"""SkillTool - Tool for agent to activate and load skills."""

from pathlib import Path

from pydantic import BaseModel

from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools
from klaude_code.skill import get_available_skills, get_skill, list_skill_names


@register(tools.SKILL)
class SkillTool(ToolABC):
    """Tool to execute/load a skill within the main conversation."""

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        """Generate schema with embedded available skills metadata."""
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
        """Generate XML format skills metadata."""
        skills = get_available_skills()
        if not skills:
            return ""

        xml_parts: list[str] = []
        for name, description, location in skills:
            xml_parts.append(f"""<skill>
<name>{name}</name>
<description>{description}</description>
<location>{location}</location>
</skill>""")
        return "\n".join(xml_parts)

    class SkillArguments(BaseModel):
        command: str

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        """Load and return full skill content."""
        try:
            args = cls.SkillArguments.model_validate_json(arguments)
        except ValueError as e:
            return model.ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )

        skill = get_skill(args.command)

        if not skill:
            available = ", ".join(list_skill_names())
            return model.ToolResultItem(
                status="error",
                output=f"Skill '{args.command}' does not exist. Available skills: {available}",
            )

        # Get base directory from skill_path
        base_dir = str(skill.skill_path.parent) if skill.skill_path else "unknown"

        # Return with loading message format
        result = f"""<command-message>The "{skill.name}" skill is activated</command-message>
<command-name>{skill.name}</command-name>

Base directory for this skill: {base_dir}

{skill.to_prompt()}"""
        return model.ToolResultItem(status="success", output=result)
