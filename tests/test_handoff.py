import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from klaude_code.agent.handoff import HandoffManager, run_handoff
from klaude_code.agent.handoff.prompts import HANDOFF_SUMMARY_PREFIX
from klaude_code.llm import LLMClientABC
from klaude_code.llm.client import LLMStreamABC
from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.models import FileStatus
from klaude_code.session.session import Session
from klaude_code.tool.handoff_tool import HandoffTool


def arun(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]

@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home

class _StaticTextStream(LLMStreamABC):
    def __init__(self, text: str) -> None:
        self._message = message.AssistantMessage(parts=[message.TextPart(text=text)], response_id=None)

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        yield self._message

    def get_partial_message(self) -> message.AssistantMessage | None:
        return self._message

class _CapturingClient(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter) -> None:
        super().__init__(config)
        self.calls: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config)

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.calls.append(param)
        return _StaticTextStream("EXTRACTED_CONTEXT")

def _text_user(text: str) -> message.UserMessage:
    return message.UserMessage(parts=message.text_parts_from_str(text))

def _text_assistant(text: str) -> message.AssistantMessage:
    return message.AssistantMessage(parts=message.text_parts_from_str(text), response_id=None)

# ---------------------------------------------------------------------------
# HandoffManager tests
# ---------------------------------------------------------------------------

class TestHandoffManager:
    def test_send_and_fetch(self) -> None:
        manager = HandoffManager()
        result = manager.send_handoff("continue auth work")
        assert result == "Handoff scheduled"

        pending = manager.fetch_pending()
        assert pending is not None
        assert pending.goal == "continue auth work"

        # After fetch, pending is cleared
        assert manager.fetch_pending() is None

    def test_double_send_raises(self) -> None:
        manager = HandoffManager()
        manager.send_handoff("goal 1")
        with pytest.raises(ValueError, match="Only one handoff"):
            manager.send_handoff("goal 2")

    def test_fetch_when_empty(self) -> None:
        manager = HandoffManager()
        assert manager.fetch_pending() is None

# ---------------------------------------------------------------------------
# run_handoff tests
# ---------------------------------------------------------------------------

class TestRunHandoff:
    def test_handoff_produces_compaction_result(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()

        async def _test() -> None:
            session = Session.create(id="handoff-test", work_dir=project_dir)
            session.file_tracker["src/auth.py"] = FileStatus(mtime=0.0)

            history: list[message.HistoryEvent] = [
                _text_user("implement auth module"),
                _text_assistant("I'll start implementing the auth module."),
                _text_user("use OAuth2"),
                _text_assistant("Switching to OAuth2 flow."),
            ]
            session.append_history(history)

            config = llm_param.LLMConfigParameter(
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="test-model",
            )
            client = _CapturingClient(config)

            goal = "finish OAuth2 implementation with PKCE and keep the existing session API"

            result = await run_handoff(
                session=session,
                goal=goal,
                llm_client=client,
                llm_config=config,
            )

            # Should discard all history
            assert result.first_kept_index == len(session.conversation_history)
            assert HANDOFF_SUMMARY_PREFIX in result.summary
            assert f"<original-handoff-goal>\n{goal}\n</original-handoff-goal>" in result.summary
            assert "EXTRACTED_CONTEXT" in result.summary
            assert result.tokens_before is not None

            # File operations should include tracked files
            assert result.details is not None
            assert "src/auth.py" in result.details.read_files

            # Verify the LLM was called with the extraction prompt
            assert len(client.calls) == 1
            call_prompt = message.join_text_parts(client.calls[0].input[0].parts)
            assert "implement auth module" in call_prompt
            assert goal in call_prompt

        arun(_test())

    def test_handoff_empty_history_raises(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()

        async def _test() -> None:
            session = Session.create(id="handoff-empty", work_dir=project_dir)
            config = llm_param.LLMConfigParameter(
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="test-model",
            )
            client = _CapturingClient(config)

            with pytest.raises(ValueError, match="No conversation history"):
                await run_handoff(
                    session=session,
                    goal="goal",
                    llm_client=client,
                    llm_config=config,
                )

        arun(_test())

    def test_handoff_result_works_with_get_llm_history(self, tmp_path: Path) -> None:
        """After appending handoff CompactionEntry, get_llm_history should return only the summary."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()

        async def _test() -> None:
            session = Session.create(id="handoff-history", work_dir=project_dir)

            history: list[message.HistoryEvent] = [
                _text_user("first message"),
                _text_assistant("first reply"),
                _text_user("second message"),
                _text_assistant("second reply"),
            ]
            session.append_history(history)

            config = llm_param.LLMConfigParameter(
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="test-model",
            )
            client = _CapturingClient(config)

            goal = "continue work with the current schema and do not change CLI flags"

            result = await run_handoff(
                session=session,
                goal=goal,
                llm_client=client,
                llm_config=config,
            )

            session.append_history([result.to_entry()])

            # get_llm_history should return just the summary as a UserMessage
            llm_history = session.get_llm_history()
            assert len(llm_history) == 1
            assert isinstance(llm_history[0], message.UserMessage)
            summary_text = message.join_text_parts(llm_history[0].parts)
            assert HANDOFF_SUMMARY_PREFIX in summary_text
            assert f"<original-handoff-goal>\n{goal}\n</original-handoff-goal>" in summary_text
            assert "EXTRACTED_CONTEXT" in summary_text

        arun(_test())

    def test_handoff_skips_system_reminders_in_serialization(self, tmp_path: Path) -> None:
        """DeveloperMessages with <system-reminder> should not appear in the serialized conversation."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()

        async def _test() -> None:
            session = Session.create(id="handoff-skip-reminders", work_dir=project_dir)

            history: list[message.HistoryEvent] = [
                _text_user("do something"),
                # Simulates a memory reminder injected by the system
                message.DeveloperMessage(
                    parts=[
                        message.TextPart(
                            text="<system-reminder>Loaded memory files. SECRET_MEMORY_CONTENT\n</system-reminder>"
                        )
                    ],
                ),
                _text_assistant("OK, doing it."),
            ]
            session.append_history(history)

            config = llm_param.LLMConfigParameter(
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="test-model",
            )
            client = _CapturingClient(config)

            await run_handoff(
                session=session,
                goal="continue",
                llm_client=client,
                llm_config=config,
            )

            # The serialized conversation sent to the LLM should not contain the reminder content
            call_prompt = message.join_text_parts(client.calls[0].input[0].parts)
            assert "SECRET_MEMORY_CONTENT" not in call_prompt
            assert "do something" in call_prompt
            assert "OK, doing it" in call_prompt

        arun(_test())

# ---------------------------------------------------------------------------
# Memory reset tests
# ---------------------------------------------------------------------------

class TestMemoryReset:
    def test_reset_attachment_loaded_flags(self) -> None:
        from klaude_code.agent.task import _reset_attachment_loaded_flags  # pyright: ignore[reportPrivateUsage]

        file_tracker: dict[str, FileStatus] = {
            "src/foo.py": FileStatus(mtime=1.0, is_memory=False),
            "/home/.claude/CLAUDE.md": FileStatus(mtime=2.0, is_memory=True),
            "/home/.claude/memory/MEMORY.md": FileStatus(mtime=3.0, is_memory=True),
            "/repo/src/.claude/skills/local/SKILL.md": FileStatus(
                mtime=3.5,
                is_skill=True,
                skill_attachment_source="dynamic",
            ),
            "/repo/.klaude-system-skill-listing": FileStatus(
                mtime=3.6,
                is_skill_listing=True,
            ),
            "/repo/src/.claude/skills/explicit/SKILL.md": FileStatus(
                mtime=3.7,
                is_skill=True,
                skill_attachment_source="explicit",
            ),
            "src/bar.py": FileStatus(mtime=4.0, is_memory=False),
        }

        _reset_attachment_loaded_flags(file_tracker)

        # Attachment-only entries should be removed
        assert "/home/.claude/CLAUDE.md" not in file_tracker
        assert "/home/.claude/memory/MEMORY.md" not in file_tracker
        assert "/repo/src/.claude/skills/local/SKILL.md" not in file_tracker
        assert "/repo/.klaude-system-skill-listing" not in file_tracker
        assert "/repo/src/.claude/skills/explicit/SKILL.md" in file_tracker
        # Non-attachment entries should remain
        assert "src/foo.py" in file_tracker
        assert "src/bar.py" in file_tracker

# ---------------------------------------------------------------------------
# HandoffTool tests
# ---------------------------------------------------------------------------

class TestHandoffTool:
    def test_schema(self) -> None:
        schema = HandoffTool.schema()
        assert schema.name == tools.HANDOFF
        assert "goal" in schema.parameters["properties"]

    def test_call_with_no_manager(self) -> None:
        from klaude_code.tool.context import TodoContext, ToolContext

        ctx = ToolContext(
            file_tracker={},
            todo_context=TodoContext(get_todos=list, set_todos=lambda x: None),
            session_id="test",
            work_dir=Path("/tmp"),
            handoff_manager=None,
        )

        async def _test() -> None:
            result = await HandoffTool.call('{"goal": "test"}', ctx)
            assert result.status == "error"
            assert "not available" in result.output_text

        arun(_test())

    def test_call_with_manager(self) -> None:
        from klaude_code.tool.context import TodoContext, ToolContext

        manager = HandoffManager()
        ctx = ToolContext(
            file_tracker={},
            todo_context=TodoContext(get_todos=list, set_todos=lambda x: None),
            session_id="test",
            work_dir=Path("/tmp"),
            handoff_manager=manager,
        )

        async def _test() -> None:
            result = await HandoffTool.call('{"goal": "continue work"}', ctx)
            assert result.status == "success"
            assert "scheduled" in result.output_text.lower()

            pending = manager.fetch_pending()
            assert pending is not None
            assert pending.goal == "continue work"

        arun(_test())
