from .skill_loader import SkillLoader
from .skill_tool import SkillTool

skill_loader = SkillLoader()
SkillTool.set_skill_loader(skill_loader)
