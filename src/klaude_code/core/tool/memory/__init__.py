from .skill_loader import SkillLoader
from .skill_tool import SkillTool
from .system_skills import install_system_skills

# Install system skills on module load (extracts bundled skills to ~/.klaude/skills/.system/)
install_system_skills()

skill_loader = SkillLoader()
SkillTool.set_skill_loader(skill_loader)
