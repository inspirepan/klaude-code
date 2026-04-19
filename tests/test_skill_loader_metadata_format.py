from pathlib import Path

from klaude_code.skill.loader import Skill, SkillLoader


def test_get_skills_xml_uses_requested_skill_block_format() -> None:
    loader = SkillLoader()
    loader.loaded_skills = {
        "system-skill": Skill(
            name="system-skill",
            description="system desc",
            location="system",
            skill_path=Path("/system/SKILL.md"),
            base_dir=Path("/system"),
        ),
        "project-skill": Skill(
            name="project-skill",
            description="project desc\nline2 & <xml>",
            location="project",
            skill_path=Path("/project/SKILL.md"),
            base_dir=Path("/project"),
        ),
        "user-skill": Skill(
            name="user-skill",
            description="user desc",
            location="user",
            skill_path=Path("/user/SKILL.md"),
            base_dir=Path("/user"),
        ),
    }

    output = loader.get_skills_xml()

    assert "<scope>" not in output
    assert "<skill>" in output
    assert "<name>project-skill</name>" in output
    assert "<description>project desc line2 &amp; &lt;xml&gt;</description>" in output
    assert "<location>/project/SKILL.md</location>" in output
    assert "<base_dir>/project</base_dir>" in output

    # Skills should keep project > user > system order.
    project_pos = output.index("<name>project-skill</name>")
    user_pos = output.index("<name>user-skill</name>")
    system_pos = output.index("<name>system-skill</name>")
    assert project_pos < user_pos < system_pos


def test_get_skills_yaml_is_backward_compatible_alias() -> None:
    loader = SkillLoader()
    loader.loaded_skills = {
        "demo": Skill(
            name="demo",
            description="demo desc",
            location="project",
            skill_path=Path("/demo/SKILL.md"),
            base_dir=Path("/demo"),
        )
    }

    assert loader.get_skills_yaml() == loader.get_skills_xml()
