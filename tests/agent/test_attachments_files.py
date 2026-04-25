from __future__ import annotations

import asyncio
from pathlib import Path

from klaude_code.agent.attachments.files import paste_file_attachment
from klaude_code.protocol import message
from klaude_code.session.session import Session


def test_paste_file_attachment_only_uses_latest_user_message(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.conversation_history = [
            message.UserMessage(
                parts=message.text_parts_from_str("first"),
                pasted_files={"paste1": str(tmp_path / "paste.txt")},
            ),
            message.AssistantMessage(parts=message.text_parts_from_str("ok")),
            message.UserMessage(parts=message.text_parts_from_str("second")),
        ]

        assert await paste_file_attachment(session) is None

    asyncio.run(_test())


def test_paste_file_attachment_is_once_per_user_message(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home

    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.conversation_history = [
            message.UserMessage(
                parts=message.text_parts_from_str("first"),
                pasted_files={"paste1": str(tmp_path / "paste.txt")},
            )
        ]

        attachment = await paste_file_attachment(session)
        assert attachment is not None
        session.conversation_history.append(attachment)

        assert await paste_file_attachment(session) is None

    asyncio.run(_test())