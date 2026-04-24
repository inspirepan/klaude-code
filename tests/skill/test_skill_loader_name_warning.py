from pathlib import Path

import pytest

from klaude_code.skill.loader import SkillLoader


def test_discover_skills_records_name_folder_mismatch_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills_root = tmp_path / "user-skills"
    skill_dir = skills_root / "folder-name"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-name\ndescription: demo\n---\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [skills_root])
    monkeypatch.setattr(SkillLoader, "PROJECT_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills(work_dir=tmp_path)

    warnings = loader.skill_warnings_by_location["user"]
    assert len(warnings) == 1
    assert warnings[0] == (
        'skill name "skill-name" should match directory name "folder-name":\n'
        f'- [user] {skill_dir / "SKILL.md"}'
    )


def test_discover_skills_no_warning_when_name_matches_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills_root = tmp_path / "user-skills"
    skill_dir = skills_root / "skill-name"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-name\ndescription: demo\n---\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [skills_root])
    monkeypatch.setattr(SkillLoader, "PROJECT_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills(work_dir=tmp_path)

    assert loader.skill_warnings_by_location["user"] == []


def test_discover_skills_falls_back_to_folder_name_when_name_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills_root = tmp_path / "user-skills"
    skill_dir = skills_root / "fallback-name"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: demo\n---\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [skills_root])
    monkeypatch.setattr(SkillLoader, "PROJECT_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills(work_dir=tmp_path)

    assert "fallback-name" in loader.loaded_skills
    assert loader.loaded_skills["fallback-name"].name == "fallback-name"
    assert loader.skill_warnings_by_location["user"] == []


def test_discover_skills_follows_subdirectory_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills_root = tmp_path / "user-skills"
    skills_root.mkdir(parents=True)
    target_dir = tmp_path / "target-skill"
    target_dir.mkdir(parents=True)
    (target_dir / "SKILL.md").write_text(
        "---\nname: link-skill\ndescription: demo\n---\n",
        encoding="utf-8",
    )

    try:
        (skills_root / "link-skill").symlink_to(target_dir, target_is_directory=True)
    except OSError as e:
        pytest.skip(f"symlink not supported in this environment: {e}")

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [skills_root])
    monkeypatch.setattr(SkillLoader, "PROJECT_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills(work_dir=tmp_path)

    assert "link-skill" in loader.loaded_skills


def test_discover_skills_records_conflict_warning_on_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    system_root = tmp_path / "system-skills"
    user_root = tmp_path / "user-skills"

    system_skill_dir = system_root / "dup-skill"
    system_skill_dir.mkdir(parents=True)
    (system_skill_dir / "SKILL.md").write_text(
        "---\nname: dup-skill\ndescription: from system\n---\n",
        encoding="utf-8",
    )

    user_skill_dir = user_root / "dup-skill"
    user_skill_dir.mkdir(parents=True)
    (user_skill_dir / "SKILL.md").write_text(
        "---\nname: dup-skill\ndescription: from user\n---\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", system_root)
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [user_root])
    monkeypatch.setattr(SkillLoader, "PROJECT_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills(work_dir=tmp_path)

    assert loader.loaded_skills["dup-skill"].location == "user"
    warnings = loader.skill_warnings_by_location["user"]
    assert len(warnings) == 1
    assert warnings[0] == (
        'duplicate "dup-skill" skill:\n'
        f"- [system] {system_skill_dir / 'SKILL.md'}\n"
        f"- [user] {user_skill_dir / 'SKILL.md'} (using this)"
    )


def test_discover_skills_no_warning_for_symlink_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When two user skill dirs find the same file via symlink, no duplicate warning should be emitted."""
    real_dir = tmp_path / "real-skills" / "my-skill"
    real_dir.mkdir(parents=True)
    (real_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: demo\n---\n",
        encoding="utf-8",
    )

    # Second user dir contains a symlink to the same skill
    link_root = tmp_path / "link-skills"
    link_root.mkdir(parents=True)
    try:
        (link_root / "my-skill").symlink_to(real_dir, target_is_directory=True)
    except OSError as e:
        pytest.skip(f"symlink not supported in this environment: {e}")

    monkeypatch.setattr(SkillLoader, "SYSTEM_SKILLS_DIR", tmp_path / "missing-system")
    monkeypatch.setattr(SkillLoader, "USER_SKILLS_DIRS", [real_dir.parent, link_root])
    monkeypatch.setattr(SkillLoader, "PROJECT_SKILLS_DIRS", [])

    loader = SkillLoader()
    loader.discover_skills(work_dir=tmp_path)

    assert "my-skill" in loader.loaded_skills
    # No duplicate warning since both paths resolve to the same file
    assert loader.skill_warnings_by_location["user"] == []
