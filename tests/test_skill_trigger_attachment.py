import asyncio
from pathlib import Path

import pytest

import klaude_code.core.agent.attachments as attachments
from klaude_code.core.agent.attachments import get_skills_from_user_input
from klaude_code.core.tool.file._utils import hash_text_sha256
from klaude_code.protocol import message, model
from klaude_code.session.session import Session
from klaude_code.skill.loader import Skill


def _arun(coro):  # type: ignore
    return asyncio.run(coro)  # type: ignore


def _build_session_with_user_text(text: str) -> Session:
    session = Session(work_dir=Path.cwd())
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str(text)))
    return session


def test_get_skill_from_slash_token() -> None:
    session = _build_session_with_user_text("please /skill:commit now")
    assert get_skills_from_user_input(session) == ["commit"]


def test_get_skill_from_double_slash_token() -> None:
    session = _build_session_with_user_text("please //skill:commit now")
    assert get_skills_from_user_input(session) == ["commit"]


def test_get_skill_ignores_path_like_slash_token() -> None:
    session = _build_session_with_user_text("/Users/root/code/project")
    assert get_skills_from_user_input(session) == []


def test_get_skill_ignores_command_name_for_slash_token() -> None:
    session = _build_session_with_user_text("/model")
    assert get_skills_from_user_input(session) == []


def test_get_skill_with_prefix_can_match_command_name() -> None:
    session = _build_session_with_user_text("/skill:model")
    assert get_skills_from_user_input(session) == ["model"]


def test_get_skill_ignores_legacy_dollar_token() -> None:
    session = _build_session_with_user_text("please $commit now")
    assert get_skills_from_user_input(session) == []


def test_get_multiple_skills_from_user_input() -> None:
    session = _build_session_with_user_text("//skill:commit  //skill:submit-pr")
    assert get_skills_from_user_input(session) == ["commit", "submit-pr"]


def test_get_skills_deduplicates() -> None:
    session = _build_session_with_user_text("/skill:commit /skill:commit")
    assert get_skills_from_user_input(session) == ["commit"]


def test_skill_attachment_tracks_skill_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_content = "# Demo Skill\n\nDo something useful.\n"
    skill_path.write_text(skill_content, encoding="utf-8")

    skill = Skill(
        name="demo",
        description="demo skill",
        location="project",
        skill_path=skill_path,
        base_dir=skill_dir,
    )

    def _mock_get_skill(_: str) -> Skill | None:
        return skill

    monkeypatch.setattr(attachments, "get_skill", _mock_get_skill)

    session = _build_session_with_user_text("/skill:demo")
    attachment = _arun(attachments.skill_attachment(session))

    assert attachment is not None
    tracked = session.file_tracker[str(skill_path)]
    assert tracked.content_sha256 == hash_text_sha256(skill_content)
    assert tracked.is_memory is False


def test_skill_attachment_loads_multiple_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills: dict[str, Skill] = {}
    for name in ("alpha", "beta"):
        skill_dir = tmp_path / name
        skill_dir.mkdir(parents=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(f"# {name} skill\n", encoding="utf-8")
        skills[name] = Skill(
            name=name,
            description=f"{name} skill",
            location="project",
            skill_path=skill_path,
            base_dir=skill_dir,
        )

    def _mock_get_skill(name: str) -> Skill | None:
        return skills.get(name)

    monkeypatch.setattr(attachments, "get_skill", _mock_get_skill)

    session = _build_session_with_user_text("//skill:alpha //skill:beta")
    attachment = _arun(attachments.skill_attachment(session))

    assert attachment is not None
    assert attachment.ui_extra is not None
    activated = [item for item in attachment.ui_extra.items if isinstance(item, model.SkillActivatedUIItem)]
    assert [item.name for item in activated] == ["alpha", "beta"]

    text = message.join_text_parts(attachment.parts)
    assert "alpha" in text
    assert "beta" in text

    assert str(skills["alpha"].skill_path) in session.file_tracker
    assert str(skills["beta"].skill_path) in session.file_tracker
