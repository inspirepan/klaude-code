"""Tests for user input inline pattern rendering."""

from typing import cast

from rich.console import Group
from rich.padding import Padding
from rich.text import Text

from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.user_input import render_at_and_skill_patterns, render_user_input


def get_spans_by_style(text: Text, style: str) -> list[str]:
    """Extract text segments that have the given style."""
    result: list[str] = []
    for span in text.spans:
        if span.style == style:
            result.append(text.plain[span.start : span.end])
    return result


def has_style(text: Text, style: str) -> bool:
    return any(span.style == style for span in text.spans)


def first_line_text(content: str) -> Text:
    rendered = render_user_input(content)
    padding = cast(Padding, rendered)
    group = cast(Group, padding.renderable)
    return cast(Text, group.renderables[0])


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
            "/skill:commit",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == ["/skill:commit"]

    def test_skill_namespace_matches_short_name(self):
        result = render_at_and_skill_patterns(
            "/skill:user:commit",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == ["/skill:user:commit"]

    def test_skill_not_highlighted_if_only_namespaced_available(self):
        result = render_at_and_skill_patterns(
            "/skill:commit",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"user:commit"},
        )
        assert get_spans_by_style(result, "SKILL") == []

    def test_skill_not_highlighted_when_invalid(self):
        result = render_at_and_skill_patterns(
            "do /skill:unknown now",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == []

    def test_slash_skill_highlighted_when_available(self):
        result = render_at_and_skill_patterns(
            "run /skill:commit now",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == ["/skill:commit"]

    def test_double_slash_skill_highlighted_when_available(self):
        result = render_at_and_skill_patterns(
            "run //skill:commit now",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == ["//skill:commit"]

    def test_slash_path_not_highlighted_as_skill(self):
        result = render_at_and_skill_patterns(
            "/Users/root/code/project",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"Users"},
        )
        assert get_spans_by_style(result, "SKILL") == []

    def test_slash_skill_conflicting_with_command_not_highlighted(self):
        result = render_at_and_skill_patterns(
            "/skill:model",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"model"},
        )
        assert get_spans_by_style(result, "SKILL") == ["/skill:model"]

    def test_legacy_dollar_skill_not_highlighted(self):
        result = render_at_and_skill_patterns(
            "$commit",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == []

    def test_requires_whitespace_boundary(self):
        result = render_at_and_skill_patterns(
            "x/skill:commit y @src/app.py",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
            available_skill_names={"commit"},
        )
        assert get_spans_by_style(result, "SKILL") == []
        assert get_spans_by_style(result, "AT") == ["@src/app.py"]

    def test_render_user_input_highlights_real_slash_command_on_first_line(self):
        line = first_line_text("/model sonnet")
        assert has_style(line, ThemeKey.USER_INPUT_SLASH_COMMAND)

    def test_render_user_input_does_not_treat_abs_path_as_slash_command(self):
        line = first_line_text("/Users/root/code/project")
        assert not has_style(line, ThemeKey.USER_INPUT_SLASH_COMMAND)
