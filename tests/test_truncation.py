# pyright: reportPrivateUsage=false
"""Tests for truncation module."""

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from klaude_code.core.tool.truncation import (
    SimpleTruncationStrategy,
    SmartTruncationStrategy,
    TruncationResult,
    _extract_url_filename,
    get_truncation_strategy,
    set_truncation_strategy,
    truncate_tool_output,
)
from klaude_code.protocol import message, tools


class TestExtractUrlFilename:
    """Test _extract_url_filename helper function."""

    def test_simple_url(self):
        """Test extracting filename from simple URL."""
        result = _extract_url_filename("https://example.com/path/to/page")
        assert result == "example_com_path_to_page"

    def test_url_without_path(self):
        """Test URL with only domain."""
        result = _extract_url_filename("https://example.com")
        assert result == "example_com"

    def test_url_with_port(self):
        """Test URL with port number."""
        result = _extract_url_filename("https://example.com:8080/api")
        assert result == "example_com_8080_api"

    def test_url_with_special_chars(self):
        """Test URL with special characters gets sanitized."""
        result = _extract_url_filename("https://example.com/path?query=value&foo=bar")
        # Query string is not part of path, so only host and path are included
        # Special chars in path would be replaced with underscore
        assert "example_com" in result
        assert "path" in result

    def test_long_url_truncation(self):
        """Test that long URLs are truncated to 80 chars."""
        long_path = "/".join(["segment"] * 20)  # Very long path
        result = _extract_url_filename(f"https://example.com{long_path}")
        assert len(result) <= 80


class TestSimpleTruncationStrategy:
    """Test SimpleTruncationStrategy class."""

    def test_no_truncation_needed(self):
        """Test output shorter than max length."""
        strategy = SimpleTruncationStrategy(max_length=100)
        result = strategy.truncate("short text")
        assert result.was_truncated is False
        assert result.output == "short text"
        assert result.original_length == 10

    def test_truncation_applied(self):
        """Test output longer than max length."""
        strategy = SimpleTruncationStrategy(max_length=20)
        long_text = "a" * 50
        result = strategy.truncate(long_text)
        assert result.was_truncated is True
        assert result.original_length == 50
        assert result.truncated_length == 30
        assert "truncated 30 characters" in result.output

    def test_exact_max_length(self):
        """Test output exactly at max length."""
        strategy = SimpleTruncationStrategy(max_length=10)
        result = strategy.truncate("0123456789")
        assert result.was_truncated is False
        assert result.output == "0123456789"

    def test_one_over_max_length(self):
        """Test output one character over max length."""
        strategy = SimpleTruncationStrategy(max_length=10)
        result = strategy.truncate("01234567890")  # 11 chars
        assert result.was_truncated is True
        assert result.truncated_length == 1


class TestSmartTruncationStrategy:
    """Test SmartTruncationStrategy class."""

    def test_no_truncation_for_short_output(self):
        """Test short output is not truncated."""
        strategy = SmartTruncationStrategy(max_length=100, head_chars=20, tail_chars=20)
        result = strategy.truncate("short text")
        assert result.was_truncated is False
        assert result.output == "short text"

    def test_read_tool_not_truncated(self):
        """Test Read tool output is never truncated."""
        strategy = SmartTruncationStrategy(max_length=10, head_chars=5, tail_chars=5)
        tool_call = message.ToolCallPart(call_id="test_id", tool_name=tools.READ, arguments_json="{}")
        long_text = "a" * 100
        result = strategy.truncate(long_text, tool_call)
        assert result.was_truncated is False
        assert result.output == long_text

    def test_truncation_shows_head_and_tail(self):
        """Test truncation shows head and tail content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = SmartTruncationStrategy(
                max_length=100,
                head_chars=10,
                tail_chars=10,
                truncation_dir=tmpdir,
            )
            # Create text with distinct head and tail
            text = "HEAD_START" + ("x" * 100) + "TAIL_ENDXX"
            result = strategy.truncate(text)

            assert result.was_truncated is True
            assert "HEAD_START" in result.output
            assert "TAIL_ENDXX" in result.output
            assert "omitted" in result.output

    def test_truncation_saves_file(self):
        """Test truncation saves full output to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = SmartTruncationStrategy(
                max_length=100,
                head_chars=10,
                tail_chars=10,
                truncation_dir=tmpdir,
            )
            text = "a" * 200
            tool_call = message.ToolCallPart(call_id="test_call_123", tool_name="TestTool", arguments_json="{}")
            result = strategy.truncate(text, tool_call)

            assert result.was_truncated is True
            assert result.saved_file_path is not None
            assert Path(result.saved_file_path).exists()
            # Verify file content
            saved_content = Path(result.saved_file_path).read_text()
            assert saved_content == text

    def test_web_fetch_uses_url_in_filename(self):
        """Test WebFetch tool uses URL for filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = SmartTruncationStrategy(
                max_length=100,
                head_chars=10,
                tail_chars=10,
                truncation_dir=tmpdir,
            )
            tool_call = message.ToolCallPart(
                call_id="fetch_123",
                tool_name=tools.WEB_FETCH,
                arguments_json='{"url": "https://example.com/page"}',
            )
            text = "a" * 200
            result = strategy.truncate(text, tool_call)

            assert result.saved_file_path is not None
            filename = Path(result.saved_file_path).name
            assert "example_com" in filename

    def test_get_file_identifier_fallback(self):
        """Test file identifier falls back to call_id."""
        strategy = SmartTruncationStrategy()
        tool_call = message.ToolCallPart(call_id="my_call_id", tool_name="SomeTool", arguments_json="{}")
        identifier = strategy._get_file_identifier(tool_call)
        assert identifier == "my_call_id"

    def test_get_file_identifier_no_tool_call(self):
        """Test file identifier when no tool call provided."""
        strategy = SmartTruncationStrategy()
        identifier = strategy._get_file_identifier(None)
        assert identifier == "unknown"

    def test_truncation_result_fields(self):
        """Test truncation result contains correct fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy = SmartTruncationStrategy(
                max_length=50,
                head_chars=10,
                tail_chars=10,
                truncation_dir=tmpdir,
            )
            text = "a" * 100
            result = strategy.truncate(text)

            assert result.original_length == 100
            assert result.truncated_length == 100 - 10 - 10  # 80 chars hidden


class TestTruncationStrategyGlobal:
    """Test global truncation strategy functions."""

    def test_get_set_strategy(self):
        """Test getting and setting truncation strategy."""
        original = get_truncation_strategy()
        try:
            new_strategy = SimpleTruncationStrategy(max_length=50)
            set_truncation_strategy(new_strategy)
            assert get_truncation_strategy() is new_strategy
        finally:
            set_truncation_strategy(original)

    def test_truncate_tool_output_uses_global_strategy(self):
        """Test truncate_tool_output uses the global strategy."""
        original = get_truncation_strategy()
        try:
            strategy = SimpleTruncationStrategy(max_length=20)
            set_truncation_strategy(strategy)
            result = truncate_tool_output("a" * 50)
            assert result.was_truncated is True
        finally:
            set_truncation_strategy(original)


class TestTruncationResult:
    """Test TruncationResult dataclass."""

    def test_default_values(self):
        """Test TruncationResult default field values."""
        result = TruncationResult(output="test", was_truncated=False)
        assert result.saved_file_path is None
        assert result.original_length == 0
        assert result.truncated_length == 0

    def test_all_fields(self):
        """Test TruncationResult with all fields."""
        result = TruncationResult(
            output="truncated",
            was_truncated=True,
            saved_file_path="/tmp/file.txt",
            original_length=1000,
            truncated_length=500,
        )
        assert result.output == "truncated"
        assert result.was_truncated is True
        assert result.saved_file_path == "/tmp/file.txt"
        assert result.original_length == 1000
        assert result.truncated_length == 500


# ============================================================================
# Property-based tests for SimpleTruncationStrategy
# ============================================================================


@given(
    text=st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=5000),
    max_length=st.integers(min_value=10, max_value=1000),
)
@settings(max_examples=100, deadline=None)
def test_simple_truncation_respects_length(text: str, max_length: int) -> None:
    """Property: truncated output length is bounded."""
    from klaude_code.core.tool.truncation import SimpleTruncationStrategy

    strategy = SimpleTruncationStrategy(max_length=max_length)
    result = strategy.truncate(text)

    if len(text) <= max_length:
        assert not result.was_truncated
        assert result.output == text
    else:
        assert result.was_truncated
        # Output starts with the truncated content
        assert result.output.startswith(text[:max_length])
        # truncated_length is correctly computed
        assert result.truncated_length == len(text) - max_length


@given(
    text=st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=1000),
    max_length=st.integers(min_value=10, max_value=500),
)
@settings(max_examples=100, deadline=None)
def test_simple_truncation_preserves_prefix(text: str, max_length: int) -> None:
    """Property: truncated output starts with prefix of original."""
    from klaude_code.core.tool.truncation import SimpleTruncationStrategy

    strategy = SimpleTruncationStrategy(max_length=max_length)
    result = strategy.truncate(text)

    if len(text) > max_length:
        assert result.output.startswith(text[:max_length])
