import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.side_question import SideQuestionError, run_side_question
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.prompts.side_question import SIDE_QUESTION_PROMPT
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import Usage
from klaude_code.session.session import Session


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


class _ScriptedStream(LLMStreamABC):
    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        self._items = items

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        for item in self._items:
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _CapturingClient(LLMClientABC):
    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-main",
            )
        )
        self._items = items
        self.calls: list[llm_param.LLMCallParameter] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        raise NotImplementedError

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        self.calls.append(param)
        return _ScriptedStream(self._items)


def _tool_schema() -> llm_param.ToolSchema:
    return llm_param.ToolSchema(name="Read", type="function", description="read a file", parameters={})


def _profile(client: _CapturingClient) -> AgentProfile:
    return AgentProfile(
        llm_client=client,
        system_prompt="MAIN SYSTEM PROMPT",
        tools=[_tool_schema()],
        attachments=[],
    )


def _session(tmp_path: Path) -> Session:
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("implement the parser")),
        message.AssistantMessage(parts=message.text_parts_from_str("done"), response_id=None),
    ]
    return session


def test_side_question_forks_the_parent_prefix_and_leaves_history_alone(tmp_path: Path) -> None:
    client = _CapturingClient([message.AssistantMessage(parts=message.text_parts_from_str(" because X. "))])
    session = _session(tmp_path)
    history_before = list(session.conversation_history)

    result = asyncio.run(
        run_side_question(session=session, main_profile=_profile(client), question="why is this cached?")
    )

    assert result.answer == "because X."
    assert session.conversation_history == history_before

    assert len(client.calls) == 1
    call = client.calls[0]
    # Cache-key components must match the parent request.
    assert call.system == "MAIN SYSTEM PROMPT"
    assert call.tools is not None
    assert [tool.name for tool in call.tools] == ["Read"]
    assert call.max_tokens is None
    # Prefix is the parent's LLM history; only the question is appended.
    prefix = [m for m in session.get_llm_history() if isinstance(m, message.Message)]
    assert call.input[: len(prefix)] == prefix
    assert len(call.input) == len(prefix) + 1
    appended = call.input[-1]
    assert isinstance(appended, message.UserMessage)
    assert message.join_text_parts(appended.parts) == SIDE_QUESTION_PROMPT.format(question="why is this cached?")


def test_side_question_reports_the_normalized_cache_hit_rate(tmp_path: Path) -> None:
    client = _CapturingClient(
        [
            message.AssistantMessage(
                parts=message.text_parts_from_str("answer"),
                response_id=None,
                # Anthropic-style totals: input_tokens already includes cached + write.
                usage=Usage(input_tokens=10_000, cached_tokens=9_000, cache_write_tokens=500, output_tokens=42),
            )
        ]
    )
    session = _session(tmp_path)

    result = asyncio.run(run_side_question(session=session, main_profile=_profile(client), question="why?"))

    assert result.cache_hit_rate == 0.9


def test_side_question_has_no_cache_hit_rate_without_usage(tmp_path: Path) -> None:
    client = _CapturingClient([message.AssistantMessage(parts=message.text_parts_from_str("answer"))])
    session = _session(tmp_path)

    result = asyncio.run(run_side_question(session=session, main_profile=_profile(client), question="why?"))

    assert result.cache_hit_rate is None


def test_side_question_patches_a_dangling_tool_call_from_the_running_turn(tmp_path: Path) -> None:
    """Mid-task the last tool call has no result yet; the request must stay valid."""
    client = _CapturingClient([message.AssistantMessage(parts=message.text_parts_from_str("answer"))])
    session = _session(tmp_path)
    session.conversation_history.append(
        message.AssistantMessage(
            parts=[message.ToolCallPart(call_id="call-1", tool_name="Read", arguments_json="{}")],
            response_id=None,
        )
    )

    asyncio.run(run_side_question(session=session, main_profile=_profile(client), question="quick one"))

    call = client.calls[0]
    tool_results = [m for m in call.input if isinstance(m, message.ToolResultMessage)]
    assert [m.call_id for m in tool_results] == ["call-1"]


def test_side_question_raises_on_stream_error(tmp_path: Path) -> None:
    client = _CapturingClient([message.StreamErrorItem(error="429 rate limited")])
    session = _session(tmp_path)

    with pytest.raises(SideQuestionError, match="429 rate limited"):
        asyncio.run(run_side_question(session=session, main_profile=_profile(client), question="why?"))


def test_side_question_raises_when_the_model_answers_with_a_tool_call_only(tmp_path: Path) -> None:
    client = _CapturingClient(
        [
            message.AssistantMessage(
                parts=[message.ToolCallPart(call_id="call-9", tool_name="Read", arguments_json="{}")],
                response_id=None,
            )
        ]
    )
    session = _session(tmp_path)

    with pytest.raises(SideQuestionError, match="no answer text"):
        asyncio.run(run_side_question(session=session, main_profile=_profile(client), question="why?"))
