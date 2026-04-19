from pathlib import Path

from klaude_code.agent.compaction import CompactionConfig, should_compact_threshold
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import Usage
from klaude_code.session.session import Session


def _llm_config(*, context_limit: int, max_tokens: int | None) -> llm_param.LLMConfigParameter:
    return llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.OPENAI,
        context_limit=context_limit,
        max_tokens=max_tokens,
    )


def test_threshold_uses_estimated_tokens_when_history_grew_after_last_usage(tmp_path: Path) -> None:
    session = Session(id="threshold-stale-usage", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="tool call")],
            usage=Usage(context_size=1_000, context_limit=2_000, max_tokens=0),
        ),
        message.ToolResultMessage(
            call_id="call-1",
            tool_name="Bash",
            status="success",
            output_text="x" * 10_000,
        ),
    ]

    should_compact = should_compact_threshold(
        session=session,
        config=CompactionConfig(reserve_tokens=200, keep_recent_tokens=1_000, max_summary_tokens=500),
        llm_config=_llm_config(context_limit=2_000, max_tokens=0),
    )

    assert should_compact is True


def test_threshold_only_estimates_increment_after_last_usage(tmp_path: Path) -> None:
    session = Session(id="threshold-increment-only", work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=[message.TextPart(text="y" * 100_000)]),
        message.AssistantMessage(
            parts=[message.TextPart(text="assistant")],
            usage=Usage(context_size=1_000, context_limit=6_000, max_tokens=0),
        ),
        message.ToolResultMessage(
            call_id="call-1",
            tool_name="Bash",
            status="success",
            output_text="z" * 120,
        ),
    ]

    should_compact = should_compact_threshold(
        session=session,
        config=CompactionConfig(reserve_tokens=500, keep_recent_tokens=1_000, max_summary_tokens=500),
        llm_config=_llm_config(context_limit=6_000, max_tokens=0),
    )

    assert should_compact is False


def test_threshold_subtracts_max_tokens_from_context_limit(tmp_path: Path) -> None:
    session = Session(id="threshold-max-tokens", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="ok")],
            usage=Usage(context_size=175_000, context_limit=200_000, max_tokens=32_000),
        )
    ]

    should_compact = should_compact_threshold(
        session=session,
        config=CompactionConfig(reserve_tokens=16_384, keep_recent_tokens=20_000, max_summary_tokens=13_107),
        llm_config=_llm_config(context_limit=200_000, max_tokens=None),
    )

    assert should_compact is True


def test_threshold_triggers_on_boundary(tmp_path: Path) -> None:
    session = Session(id="threshold-boundary", work_dir=tmp_path)
    session.conversation_history = [
        message.AssistantMessage(
            parts=[message.TextPart(text="ok")],
            usage=Usage(context_size=151_616, context_limit=200_000, max_tokens=32_000),
        )
    ]

    should_compact = should_compact_threshold(
        session=session,
        config=CompactionConfig(reserve_tokens=16_384, keep_recent_tokens=20_000, max_summary_tokens=13_107),
        llm_config=_llm_config(context_limit=200_000, max_tokens=None),
    )

    assert should_compact is True
