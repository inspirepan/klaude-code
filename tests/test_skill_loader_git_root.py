from pathlib import Path

import pytest

from klaude_code.skill.loader import SkillLoader


def test_discover_skills_includes_git_root_project_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    work_dir = repo_root / "apps" / "service"
    work_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    root_skill_file = repo_root / ".claude" / "skills" / "root-skill" / "SKILL.md"
    root_skill_file.parent.mkdir(parents=True)
    root_skill_file.write_text(
        "---\nname: root-skill\ndescription: from git root\n---\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(work_dir)
    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills()

    assert "root-skill" in loader.loaded_skills
    assert loader.loaded_skills["root-skill"].location == "project"


def test_discover_skills_prefers_cwd_project_skill_over_git_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = tmp_path / "repo"
    work_dir = repo_root / "apps" / "service"
    work_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    root_skill_file = repo_root / ".claude" / "skills" / "shared-skill" / "SKILL.md"
    root_skill_file.parent.mkdir(parents=True)
    root_skill_file.write_text(
        "---\nname: shared-skill\ndescription: from git root\n---\n",
        encoding="utf-8",
    )

    cwd_skill_file = work_dir / ".claude" / "skills" / "shared-skill" / "SKILL.md"
    cwd_skill_file.parent.mkdir(parents=True)
    cwd_skill_file.write_text(
        "---\nname: shared-skill\ndescription: from cwd\n---\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(work_dir)
    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills()

    assert "shared-skill" in loader.loaded_skills
    assert loader.loaded_skills["shared-skill"].description == "from cwd"
    warnings = loader.skill_warnings_by_location["project"]
    assert len(warnings) == 1
    assert 'duplicate skill "shared-skill"' in warnings[0]
