from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from klaude_code.agent.attachments.autonomy import autonomy_attachment
from klaude_code.agent.attachments.state import reset_attachment_loaded_flags
from klaude_code.protocol import message
from klaude_code.server.headless import format_tool_call_activity
from klaude_code.server.routes.headless import _resolve_target  # pyright: ignore[reportPrivateUsage]
from klaude_code.server.session_index import SessionSummary
from klaude_code.session.session import Session


def _summary(session_id: str, *, name: str | None = None, archived: bool = False) -> SessionSummary:
    return SessionSummary(
        id=session_id,
        created_at=1.0,
        updated_at=2.0,
        work_dir="/tmp/x",
        title=None,
        user_messages=[],
        messages_count=0,
        model_name=None,
        session_state=None,
        runtime_owner=None,
        runtime_owner_heartbeat_at=None,
        archived=archived,
        todos=[],
        file_change_summary={},
        name=name,
    )


class TestResolveTarget:
    def test_exact_id(self) -> None:
        summaries = [_summary("abcd1234"), _summary("abzz9999")]
        assert _resolve_target(summaries, "abcd1234").id == "abcd1234"

    def test_unique_prefix(self) -> None:
        summaries = [_summary("abcd1234"), _summary("efgh5678")]
        assert _resolve_target(summaries, "ab").id == "abcd1234"

    def test_name_match_beats_prefix(self) -> None:
        summaries = [_summary("abcd1234"), _summary("efgh5678", name="abcd")]
        assert _resolve_target(summaries, "abcd").id == "efgh5678"

    def test_ambiguous_prefix_lists_candidates(self) -> None:
        summaries = [_summary("abcd1234"), _summary("abzz9999")]
        with pytest.raises(HTTPException) as exc_info:
            _resolve_target(summaries, "ab")
        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert set(detail["candidates"]) == {"abcd1234", "abzz9999"}

    def test_archived_name_yields_to_active(self) -> None:
        summaries = [_summary("abcd1234", name="dup", archived=True), _summary("efgh5678", name="dup")]
        assert _resolve_target(summaries, "dup").id == "efgh5678"

    def test_unknown_target_404(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _resolve_target([_summary("abcd1234")], "zzzz")
        assert exc_info.value.status_code == 404


class TestFormatToolCallActivity:
    def test_extracts_primary_argument(self) -> None:
        assert format_tool_call_activity("Bash", '{"command": "uv run pytest"}') == "Bash: uv run pytest"

    def test_truncates_long_arguments(self) -> None:
        label = format_tool_call_activity("Bash", '{"command": "' + "x" * 200 + '"}', max_len=40)
        assert len(label) == 40
        assert label.endswith("…")

    def test_non_json_arguments(self) -> None:
        assert format_tool_call_activity("Edit", "not json") == "Edit: not json"

    def test_no_arguments(self) -> None:
        assert format_tool_call_activity("TodoWrite", "") == "TodoWrite"


class TestAutonomyAttachment:
    def test_injects_once_for_headless(self, tmp_path: Path) -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        first = asyncio.run(autonomy_attachment(session))
        assert first is not None
        part = first.parts[0]
        assert isinstance(part, message.TextPart)
        assert "running unattended" in part.text
        assert asyncio.run(autonomy_attachment(session)) is None

    def test_skips_interactive_sessions(self, tmp_path: Path) -> None:
        session = Session.create(work_dir=tmp_path)
        assert asyncio.run(autonomy_attachment(session)) is None

    def test_reinjects_after_compaction_reset(self, tmp_path: Path) -> None:
        session = Session.create(work_dir=tmp_path)
        session.spawn_kind = "headless"
        assert asyncio.run(autonomy_attachment(session)) is not None
        reset_attachment_loaded_flags(session.file_tracker)
        assert asyncio.run(autonomy_attachment(session)) is not None
