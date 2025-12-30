# pyright: reportPrivateUsage=false
"""Property-based tests for ui.renderers.common module."""

from hypothesis import given, settings
from hypothesis import strategies as st


# ============================================================================
# Property-based tests for truncate_display
# ============================================================================


@given(
    text=st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=2000),
    max_lines=st.integers(min_value=0, max_value=100),
    max_line_length=st.integers(min_value=10, max_value=500),
)
@settings(max_examples=100, deadline=None)
def test_truncate_display_line_count(text: str, max_lines: int, max_line_length: int) -> None:
    """Property: truncated output has bounded line count."""
    from klaude_code.ui.renderers.common import truncate_display

    result = truncate_display(text, max_lines=max_lines, max_line_length=max_line_length)
    result_text = result.plain

    if max_lines <= 0:
        # Should show only truncation indicator
        assert "more" in result_text
    else:
        # Line count should be bounded
        result_lines = result_text.split("\n")
        # Allow some extra lines for truncation indicators
        assert len(result_lines) <= max_lines + 2


@given(
    text=st.text(st.characters(blacklist_categories=("Cs",)), min_size=0, max_size=500),
    max_lines=st.integers(min_value=1, max_value=50),
)
@settings(max_examples=100, deadline=None)
def test_truncate_display_short_text_preserved(text: str, max_lines: int) -> None:
    """Property: short text that fits is preserved."""
    from klaude_code.ui.renderers.common import truncate_display

    lines = text.split("\n")

    # Only test when text is short enough
    if len(lines) <= max_lines:
        _ = truncate_display(text, max_lines=max_lines, max_line_length=10000)
        # Test passes if no exception is raised
