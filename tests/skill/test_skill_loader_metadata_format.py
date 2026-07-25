from pathlib import Path

from klaude_code.skill.loader import Skill, SkillLoader, extract_skill_listing_paths_from_xml


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
    assert '<skill name="project-skill" path="/project/SKILL.md">project desc line2 &amp; &lt;xml&gt;</skill>' in output
    # base_dir is the parent of SKILL.md here, so it is left implicit.
    assert "base_dir" not in output
    # One line per skill keeps this always-in-context listing small.
    assert len(output.splitlines()) == 3

    # Skills should keep project > user > system order.
    project_pos = output.index("project-skill")
    user_pos = output.index("user-skill")
    system_pos = output.index("system-skill")
    assert project_pos < user_pos < system_pos


def test_get_skills_xml_emits_base_dir_only_when_it_differs_from_skill_dir() -> None:
    loader = SkillLoader()
    loader.loaded_skills = {
        "linked": Skill(
            name="linked",
            description="reached through a symlink",
            location="project",
            skill_path=Path("/real/place/SKILL.md"),
            base_dir=Path("/linked/place"),
        )
    }

    assert 'base_dir="/linked/place"' in loader.get_skills_xml()


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


def test_extract_skill_listing_paths_round_trips_current_format() -> None:
    loader = SkillLoader()
    loader.loaded_skills = {
        "demo": Skill(
            name="demo",
            description="desc with & <entities>",
            location="project",
            skill_path=Path("/demo/SKILL.md"),
            base_dir=Path("/demo"),
        )
    }

    assert extract_skill_listing_paths_from_xml(loader.get_skills_xml()) == {"demo": "/demo/SKILL.md"}


def test_extract_skill_listing_paths_still_reads_legacy_nested_format() -> None:
    """Sessions persisted before the one-line listing must keep their skill-listing state."""
    legacy = (
        "  <skill>\n"
        "    <name>demo</name>\n"
        "    <description>desc</description>\n"
        "    <location>/demo/SKILL.md</location>\n"
        "    <base_dir>/demo</base_dir>\n"
        "  </skill>"
    )

    assert extract_skill_listing_paths_from_xml(legacy) == {"demo": "/demo/SKILL.md"}
