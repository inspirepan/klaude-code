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

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills(work_dir=work_dir)

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

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills(work_dir=work_dir)

    assert "shared-skill" in loader.loaded_skills
    assert loader.loaded_skills["shared-skill"].description == "from cwd"
    warnings = loader.skill_warnings_by_location["project"]
    assert len(warnings) == 1
    assert warnings[0] == (
        f'duplicate "shared-skill" skill:\n- [project] {root_skill_file}\n- [project] {cwd_skill_file} (using this)'
    )


@pytest.mark.parametrize("skills_dir", [".claude", ".agents"])
@pytest.mark.parametrize("with_git", [False, True])
def test_discover_skills_includes_ancestors_above_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skills_dir: str, with_git: bool
) -> None:
    repo_root = tmp_path / "workspace" / "repo"
    work_dir = repo_root / "apps" / "service"
    work_dir.mkdir(parents=True)
    if with_git:
        (repo_root / ".git").mkdir()

    for ancestor in (tmp_path, repo_root / "apps"):
        skill_file = ancestor / skills_dir / "skills" / ancestor.name / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text(f"---\nname: {ancestor.name}\ndescription: inherited\n---\n", encoding="utf-8")

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [])
    loader = SkillLoader()
    loader.discover_skills(work_dir)

    assert loader.loaded_skills[tmp_path.name].location == "project"
    assert loader.loaded_skills["apps"].location == "project"


@pytest.mark.parametrize("levels", [1, 2, 3, 4])
def test_discover_skills_prefers_nearer_ancestors_then_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, levels: int
) -> None:
    repo_root = tmp_path / "repo"
    work_dir = repo_root / "apps" / "service"
    work_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()
    candidates = [
        tmp_path / ".agents" / "skills",
        repo_root / ".claude" / "skills",
        repo_root / "apps" / ".claude" / "skills",
        repo_root / "apps" / ".agents" / "skills",
    ]
    for directory in candidates[:levels]:
        skill_file = directory / "shared" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("---\nname: shared\ndescription: shared skill\n---\n", encoding="utf-8")

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [])
    loader = SkillLoader()
    loader.discover_skills(work_dir)

    assert loader.loaded_skills["shared"].skill_path == candidates[levels - 1] / "shared" / "SKILL.md"


def test_discover_skills_does_not_reload_user_dirs_as_project(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_dir = isolated_home / "workspace" / "repo"
    work_dir.mkdir(parents=True)
    for directory in (".claude", ".agents"):
        skill_file = isolated_home / directory / "skills" / "shared" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("---\nname: shared\ndescription: user skill\n---\n", encoding="utf-8")

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", isolated_home / "missing-system")
    loader = SkillLoader()
    skills = loader.discover_skills(work_dir)

    assert len(skills) == 2
    assert all(skill.location == "user" for skill in skills)
    assert loader.loaded_skills["shared"].skill_path == isolated_home / ".agents/skills/shared/SKILL.md"
    assert not loader.skill_warnings_by_location["project"]


def test_discover_skills_preserves_priority_for_symlinked_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_dir = tmp_path / "repo"
    (work_dir / ".git").mkdir(parents=True)
    for directory in (".claude", ".agents"):
        skill_file = work_dir / directory / "skills" / "shared" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("---\nname: shared\ndescription: shared skill\n---\n", encoding="utf-8")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "skills").symlink_to(work_dir / ".agents" / "skills", target_is_directory=True)

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [])
    loader = SkillLoader()
    skills = loader.discover_skills(work_dir)

    assert len(skills) == 2
    assert loader.loaded_skills["shared"].skill_path == work_dir / ".agents/skills/shared/SKILL.md"
