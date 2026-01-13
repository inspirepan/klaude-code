"""Tests for user input inline pattern rendering."""

from rich.text import Text

from klaude_code.tui.components.user_input import render_at_and_skill_patterns


def get_spans_by_style(text: Text, style: str) -> list[str]:
    """Extract text segments that have the given style."""
    result: list[str] = []
    for span in text.spans:
        if span.style == style:
            result.append(text.plain[span.start : span.end])
    return result


class TestRenderAtAndSkillPatterns:
    def test_at_file_highlighted(self):
        result = render_at_and_skill_patterns("@src/app.py", at_style="AT", skill_style="SKILL", other_style="OTHER")
        assert get_spans_by_style(result, "AT") == ["@src/app.py"]

    def test_at_quoted_file_highlighted(self):
        result = render_at_and_skill_patterns(
            '@"src/my file.py"',
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
        )
        assert get_spans_by_style(result, "AT") == ['@"src/my file.py"']

    def test_no_email_false_positive(self):
        result = render_at_and_skill_patterns("foo@bar.com", at_style="AT", skill_style="SKILL", other_style="OTHER")
        assert get_spans_by_style(result, "AT") == []

    def test_skill_highlighted_when_available(self):
        result = render_at_and_skill_patterns(
            "$commit",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == ["$commit"]

    def test_skill_namespace_matches_short_name(self):
        result = render_at_and_skill_patterns(
            "$user:commit",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == ["$user:commit"]

    def test_skill_not_highlighted_if_only_namespaced_available(self):
        result = render_at_and_skill_patterns(
            "$commit",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"user:commit"},
        )
        assert get_spans_by_style(result, "SKILL") == []

    def test_skill_not_highlighted_when_invalid(self):
        result = render_at_and_skill_patterns(
            "do $unknown now",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == []

    def test_requires_whitespace_boundary(self):
        result = render_at_and_skill_patterns(
            "x$commit y @src/app.py",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == []
        assert get_spans_by_style(result, "AT") == ["@src/app.py"]
