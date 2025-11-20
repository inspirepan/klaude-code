from pydantic import BaseModel

from klaude_code.core.tool.skill_loader import SkillLoader
from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import ToolResultItem
from klaude_code.protocol.tools import SKILL


@register(SKILL)
class SkillTool(ToolABC):
    """Tool to execute/load a skill within the main conversation"""

    _skill_loader: SkillLoader | None = None

    @classmethod
    def set_skill_loader(cls, loader: SkillLoader) -> None:
        """Set the skill loader instance"""
        cls._skill_loader = loader

    @classmethod
    def schema(cls) -> ToolSchema:
        """Generate schema with embedded available skills metadata"""
        skills_xml = cls._generate_skills_xml()

        return ToolSchema(
            name=SKILL,
            type="function",
            description=f"""Execute a skill within the main conversation

<skills_instructions>
When users ask you to perform tasks, check if any of the available skills below can help complete the task more effectively. Skills provide specialized capabilities and domain knowledge.

How to use skills:
- Invoke skills using this tool with the skill name only (no arguments)
- When you invoke a skill, you will see <command-message>The "{{name}}" skill is loading</command-message>
- The skill's prompt will expand and provide detailed instructions on how to complete the task

Examples:
- command: "pdf" - invoke the pdf skill
- command: "xlsx" - invoke the xlsx skill
- command: "document-skills:pdf" - invoke using fully qualified name

Important:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already running
- Do not use this tool for built-in CLI commands (like /help, /clear, etc.)
</skills_instructions>

<available_skills>
{skills_xml}
</available_skills>""",
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
    async def call(cls, arguments: str) -> ToolResultItem:
        """Load and return full skill content"""
        try:
            args = cls.SkillArguments.model_validate_json(arguments)
        except ValueError as e:
            return ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )

        if not cls._skill_loader:
            return ToolResultItem(
                status="error",
                output="Skill loader not initialized",
            )

        skill = cls._skill_loader.get_skill(args.command)

        if not skill:
            available = ", ".join(cls._skill_loader.list_skills())
            return ToolResultItem(
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
        return ToolResultItem(status="success", output=result)
