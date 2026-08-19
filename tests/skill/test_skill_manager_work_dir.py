"""Regression tests: skill manager access is keyed by work_dir, not process CWD.

The server process hosts sessions rooted in different directories; the old
CWD-bound singleton showed every session the skills of whatever directory
first spawned the server.
"""

from pathlib import Path

import pytest

from klaude_code.skill import manager
from klaude_code.skill.loader import SkillLoader


def _write_project_skill(project_dir: Path, name: str) -> None:
    skill_file = project_dir / ".claude" / "skills" / name / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(f"---\nname: {name}\ndescription: project skill\n---\n", encoding="utf-8")


@pytest.fixture
def isolated_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [])
    monkeypatch.setattr(manager, "install_system_skills", lambda: None)
    monkeypatch.setattr(manager, "_loaders", {})


def test_available_skills_are_per_work_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_manager: None
) -> None:
    del isolated_manager
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    _write_project_skill(project_a, "skill-a")
    _write_project_skill(project_b, "skill-b")

    # The process CWD points at neither project.
    server_cwd = tmp_path / "server-cwd"
    server_cwd.mkdir()
    monkeypatch.chdir(server_cwd)

    names_a = {name for name, _desc, _loc in manager.get_available_skills(project_a)}
    names_b = {name for name, _desc, _loc in manager.get_available_skills(project_b)}

    assert names_a == {"skill-a"}
    assert names_b == {"skill-b"}


def test_loader_cache_is_keyed_by_resolved_work_dir(tmp_path: Path, isolated_manager: None) -> None:
    del isolated_manager
    project = tmp_path / "project"
    project.mkdir()
    _write_project_skill(project, "cached-skill")

    first = manager.get_skill_loader(project)
    second = manager.get_skill_loader(project / "." / "..")
    assert first is manager.get_skill_loader(project)
    assert second is not first  # parent dir is a different workspace

    assert manager.get_skill("cached-skill", project) is not None
    assert manager.list_skill_names(project) == ["cached-skill"]
