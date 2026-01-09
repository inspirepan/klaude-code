import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from klaude_code.core.compaction import CompactionReason, run_compaction
from klaude_code.core.compaction.prompts import COMPACTION_SUMMARY_PREFIX, TASK_PREFIX_SUMMARIZATION_PROMPT
from klaude_code.llm import LLMClientABC
from klaude_code.llm.client import LLMStreamABC
from klaude_code.protocol import llm_param, message, model
from klaude_code.session.session import Session, close_default_store


def arun(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate user home to keep session persistence under tmp_path."""

    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)


class _StaticTextStream(LLMStreamABC):
    def __init__(self, text: str) -> None:
        self._message = message.AssistantMessage(parts=[message.TextPart(text=text)], response_id=None)

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        yield self._message

    def get_partial_message(self) -> message.AssistantMessage | None:
        return self._message


class _CapturingSummarizerClient(LLMClientABC):
    """Deterministic LLM client stub for compaction.

    Returns different summaries for task-prefix vs history-summary calls.
    Captures call params for assertions.
    """

    def __init__(self, config: llm_param.LLMConfigParameter) -> None:
        super().__init__(config)
        self.calls: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config)

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.calls.append(param)

        full_prompt = "\n".join(
            message.join_text_parts(m.parts) for m in param.input if isinstance(m, message.UserMessage)
        )
        if TASK_PREFIX_SUMMARIZATION_PROMPT in full_prompt:
            return _StaticTextStream("TASK_PREFIX_SUMMARY")
        return _StaticTextStream("HISTORY_SUMMARY")


def _text_user(text: str) -> message.UserMessage:
    return message.UserMessage(parts=message.text_parts_from_str(text))


def _text_assistant(text: str) -> message.AssistantMessage:
    return message.AssistantMessage(parts=message.text_parts_from_str(text), response_id=None)


def test_compaction_end_to_end_summary_and_llm_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(id="compaction-e2e", work_dir=project_dir)

        # Used by _collect_file_operations() as read files.
        session.file_tracker["docs/a.md"] = model.FileStatus(mtime=0.0)

        # Build a history that triggers split-task compaction:
        # - Old history (to summarize) includes tool calls/results and large outputs.
        # - New task user message is the boundary.
        # - Recent assistant message is large enough to become the kept boundary.
        history_items: list[message.HistoryEvent] = [
            _text_user("old user: " + ("u" * 2500)),
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(call_id="call_read", tool_name="read", arguments_json='{"file_path":"docs/a.md"}'),
                    message.TextPart(text="about to read"),
                ],
                response_id=None,
            ),
            message.ToolResultMessage(
                call_id="call_read",
                tool_name="read",
                status="success",
                output_text="x" * 5000,
            ),
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(
                        call_id="call_edit",
                        tool_name="edit",
                        arguments_json='{"file_path":"src/foo.py","old":"a","new":"b"}',
                    ),
                    message.TextPart(text="patched"),
                ],
                response_id=None,
            ),
            message.ToolResultMessage(
                call_id="call_edit",
                tool_name="edit",
                status="success",
                output_text="ok",
                ui_extra=model.DiffUIExtra(files=[model.DiffFileDiff(file_path="src/foo.py", lines=[], stats_add=1)]),
            ),
            _text_user("new task: implement foo"),
            _text_assistant("recent assistant: " + ("r" * 5000)),
            _text_assistant("tail"),
        ]
        session.append_history(history_items)
        await session.wait_for_flush()

        llm_config = llm_param.LLMConfigParameter(
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="dummy",
            context_limit=3000,
        )
        llm_client = _CapturingSummarizerClient(llm_config)

        result = await run_compaction(
            session=session,
            reason=CompactionReason.MANUAL,
            focus="preserve key context",
            llm_client=llm_client,
            llm_config=llm_config,
        )

        # Persist compaction entry (as production does).
        session.append_history([result.to_entry()])
        await session.wait_for_flush()

        assert result.first_kept_index > 0
        assert COMPACTION_SUMMARY_PREFIX in result.summary
        assert "HISTORY_SUMMARY" in result.summary
        assert "TASK_PREFIX_SUMMARY" in result.summary

        # File operations are appended after the summary.
        assert "<read-files>" in result.summary
        assert "docs/a.md" in result.summary
        assert "<modified-files>" in result.summary
        assert "src/foo.py" in result.summary

        # The end-to-end chain: Session.get_llm_history injects the summary as a UserMessage.
        llm_history = session.get_llm_history()
        assert llm_history
        assert isinstance(llm_history[0], message.UserMessage)
        assert message.join_text_parts(llm_history[0].parts) == result.summary

        # The first kept message should be the boundary; in this setup it must not be a ToolResultMessage.
        assert len(llm_history) >= 2
        assert not isinstance(llm_history[1], message.ToolResultMessage)
        assert isinstance(llm_history[1], message.AssistantMessage)

        # Verify we actually exercised the split-task path (2 summarizer calls).
        assert len(llm_client.calls) == 2

        # The history-summary call should include truncated tool output in its <conversation>.
        prompts = [
            "\n".join(
                message.join_text_parts(m.parts) for m in call.input if isinstance(m, message.UserMessage)
            )
            for call in llm_client.calls
        ]
        assert any("[Tool result]:" in p and "...(truncated)" in p for p in prompts)
        assert any(TASK_PREFIX_SUMMARIZATION_PROMPT in p for p in prompts)

        await close_default_store()

    arun(_test())
