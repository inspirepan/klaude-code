# pyright: reportPrivateUsage=false
"""Tests for tool output offload module."""

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from klaude_code.core.tool.offload import (
    HeadTailOffloadStrategy,
    OffloadPolicy,
    OffloadResult,
    ReadToolStrategy,
    get_strategy,
    offload_tool_output,
)
from klaude_code.protocol import message, tools


class TestReadToolStrategy:
    """Test ReadToolStrategy - pass-through for Read tool output."""

    def test_never_truncates(self):
        strategy = ReadToolStrategy()
        long_text = "a" * 100000
        result = strategy.process(long_text)
        assert result.was_truncated is False
        assert result.output == long_text

    def test_offload_policy_is_never(self):
        strategy = ReadToolStrategy()
        assert strategy.offload_policy == OffloadPolicy.NEVER


class TestHeadTailOffloadStrategy:
    """Test HeadTailOffloadStrategy for Bash and generic tools."""

    def test_no_truncation_for_short_output(self):
        strategy = HeadTailOffloadStrategy(max_length=100, head_chars=20, tail_chars=20)
        result = strategy.process("short text")
        assert result.was_truncated is False
        assert result.output == "short text"

    def test_truncation_shows_head_and_tail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = HeadTailOffloadStrategy(
                max_length=100,
                head_chars=10,
                tail_chars=10,
                offload_dir=tmpdir,
            )
            text = "HEAD_START" + ("x" * 100) + "TAIL_ENDXX"
            result = strategy.process(text)

            assert result.was_truncated is True
            assert "HEAD_START" in result.output
            assert "TAIL_ENDXX" in result.output
            assert "omitted" in result.output

    def test_truncation_saves_file_on_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = HeadTailOffloadStrategy(
                max_length=100,
                head_chars=10,
                tail_chars=10,
                offload_dir=tmpdir,
                policy=OffloadPolicy.ON_THRESHOLD,
            )
            text = "a" * 200
            tool_call = message.ToolCallPart(call_id="test_call_123", tool_name="TestTool", arguments_json="{}")
            result = strategy.process(text, tool_call)

            assert result.was_truncated is True
            assert result.offloaded_path is not None
            assert Path(result.offloaded_path).exists()
            saved_content = Path(result.offloaded_path).read_text()
            assert saved_content == text

    def test_no_offload_when_policy_never(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = HeadTailOffloadStrategy(
                max_length=100,
                head_chars=10,
                tail_chars=10,
                offload_dir=tmpdir,
                policy=OffloadPolicy.NEVER,
            )
            text = "a" * 200
            result = strategy.process(text)

            assert result.was_truncated is True
            assert result.offloaded_path is None

    def test_result_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = HeadTailOffloadStrategy(
                max_length=50,
                head_chars=10,
                tail_chars=10,
                offload_dir=tmpdir,
            )
            text = "a" * 100
            result = strategy.process(text)

            assert result.original_length == 100
            assert result.truncated_chars == 100 - 10 - 10


class TestStrategyRegistry:
    """Test strategy selection via get_strategy."""

    def test_read_tool_gets_read_strategy(self):
        strategy = get_strategy(tools.READ)
        assert isinstance(strategy, ReadToolStrategy)

    def test_web_fetch_gets_default_strategy(self):
        strategy = get_strategy(tools.WEB_FETCH)
        assert isinstance(strategy, HeadTailOffloadStrategy)

    def test_bash_gets_head_tail_strategy(self):
        strategy = get_strategy(tools.BASH)
        assert isinstance(strategy, HeadTailOffloadStrategy)

    def test_unknown_tool_gets_default(self):
        strategy = get_strategy("UnknownTool")
        assert isinstance(strategy, HeadTailOffloadStrategy)

    def test_none_gets_default(self):
        strategy = get_strategy(None)
        assert isinstance(strategy, HeadTailOffloadStrategy)


class TestOffloadToolOutput:
    """Test main entry point offload_tool_output."""

    def test_read_tool_not_truncated(self):
        tool_call = message.ToolCallPart(call_id="test_id", tool_name=tools.READ, arguments_json="{}")
        long_text = "a" * 100000
        result = offload_tool_output(long_text, tool_call)
        assert result.was_truncated is False
        assert result.output == long_text

    def test_bash_tool_truncated_and_offloaded(self):
        tool_call = message.ToolCallPart(call_id="test_id", tool_name=tools.BASH, arguments_json="{}")
        long_text = "a" * 100000
        result = offload_tool_output(long_text, tool_call)
        assert result.was_truncated is True
        assert result.offloaded_path is not None

    def test_web_fetch_uses_default_strategy(self):
        tool_call = message.ToolCallPart(
            call_id="test_id",
            tool_name=tools.WEB_FETCH,
            arguments_json='{"url": "https://example.com"}',
        )
        short_text = "small content"
        result = offload_tool_output(short_text, tool_call)
        # WebFetch now uses default strategy (ON_THRESHOLD), so short text is not offloaded
        assert result.was_truncated is False
        assert result.offloaded_path is None


class TestOffloadResult:
    """Test OffloadResult dataclass."""

    def test_default_values(self):
        result = OffloadResult(output="test", was_truncated=False)
        assert result.offloaded_path is None
        assert result.original_length == 0
        assert result.truncated_chars == 0

    def test_all_fields(self):
        result = OffloadResult(
            output="truncated",
            was_truncated=True,
            offloaded_path="/tmp/file.txt",
            original_length=1000,
            truncated_chars=500,
        )
        assert result.output == "truncated"
        assert result.was_truncated is True
        assert result.offloaded_path == "/tmp/file.txt"
        assert result.original_length == 1000
        assert result.truncated_chars == 500


# ============================================================================
# Property-based tests
# ============================================================================


@given(
    text=st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=5000),
    max_length=st.integers(min_value=100, max_value=1000),
)
@settings(max_examples=100, deadline=None)
def test_head_tail_truncation_preserves_bounds(text: str, max_length: int) -> None:
    """Property: truncated output respects head/tail bounds (char-based)."""
    head_chars = max_length // 4
    tail_chars = max_length // 4
    # Set max_lines very high to only test char-based truncation
    strategy = HeadTailOffloadStrategy(
        max_length=max_length, head_chars=head_chars, tail_chars=tail_chars, max_lines=100000
    )
    result = strategy.process(text)

    if len(text) <= max_length:
        assert not result.was_truncated
        assert result.output == text
    else:
        assert result.was_truncated
        assert text[:head_chars] in result.output
        assert text[-tail_chars:] in result.output
