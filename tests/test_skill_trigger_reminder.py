from pathlib import Path

from klaude_code.core.reminders import get_skill_from_user_input
from klaude_code.protocol import message
from klaude_code.session.session import Session


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
