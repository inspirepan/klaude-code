import asyncio
from pathlib import Path

import pytest

from klaude_code.core import reminders
from klaude_code.core.reminders import get_skill_from_user_input
from klaude_code.core.tool.file._utils import hash_text_sha256
from klaude_code.protocol import message
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
    assert get_skill_from_user_input(session) == "commit"


def test_get_skill_from_double_slash_token() -> None:
    session = _build_session_with_user_text("please //skill:commit now")
    assert get_skill_from_user_input(session) == "commit"


def test_get_skill_ignores_path_like_slash_token() -> None:
    session = _build_session_with_user_text("/Users/root/code/project")
    assert get_skill_from_user_input(session) is None


def test_get_skill_ignores_command_name_for_slash_token() -> None:
    session = _build_session_with_user_text("/model")
    assert get_skill_from_user_input(session) is None


def test_get_skill_with_prefix_can_match_command_name() -> None:
    session = _build_session_with_user_text("/skill:model")
    assert get_skill_from_user_input(session) == "model"


def test_get_skill_ignores_legacy_dollar_token() -> None:
    session = _build_session_with_user_text("please $commit now")
    assert get_skill_from_user_input(session) is None


def test_skill_reminder_tracks_skill_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(reminders, "get_skill", lambda _: skill)

    session = _build_session_with_user_text("/skill:demo")
    reminder = _arun(reminders.skill_reminder(session))

    assert reminder is not None
    tracked = session.file_tracker[str(skill_path)]
    assert tracked.content_sha256 == hash_text_sha256(skill_content)
    assert tracked.is_memory is False
