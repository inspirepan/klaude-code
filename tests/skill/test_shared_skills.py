from pathlib import Path

import pytest

from klaude_code.skill import manager
from klaude_code.skill.loader import SkillLoader


def test_shared_symlink_loads_without_installing_hidden_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    shared = home / ".agents/skills"
    legacy = home / ".klaude/skills"
    source = tmp_path / "source/demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: demo\ndescription: shared\n---\n")
    shared.mkdir(parents=True)
    (shared / "demo").symlink_to(source, target_is_directory=True)
    for name in (".system", ".private"):
        hidden = legacy / name / "hidden"
        hidden.mkdir(parents=True)
        (hidden / "SKILL.md").write_text("---\nname: hidden\ndescription: hidden\n---\n")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [legacy, shared])
    monkeypatch.setattr(SkillLoader, "PROJECT_SKILLS_DIRS", [])
    before = {str(path.relative_to(home)) for path in home.rglob("*")}
    loader = manager.get_skill_loader(tmp_path / "project")
    assert list(loader.loaded_skills) == ["demo"]
    assert loader.loaded_skills["demo"].location == "user"
    assert loader.loaded_skills["demo"].skill_path == source / "SKILL.md"
    assert {str(path.relative_to(home)) for path in home.rglob("*")} == before
