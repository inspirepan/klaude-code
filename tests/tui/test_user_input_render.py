"""Tests for user input inline pattern rendering."""

from rich.console import Console
from rich.segment import Segment
from rich.text import Text

from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.components.user_input import (
    build_user_input_lines,
    render_at_and_skill_patterns,
    render_user_input,
)


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
    return build_user_input_lines(content)[0]


def rendered_lines(content: str) -> list[str]:
    console = Console(width=200, record=True, theme=get_theme().app_theme)
    console.print(render_user_input(content))
    return [line.rstrip() for line in console.export_text(styles=False).splitlines()]


def rendered_segments(content: str, width: int = 200) -> list[list[Segment]]:
    console = Console(width=width, record=False, theme=get_theme().app_theme)
    return list(Segment.split_lines(console.render(render_user_input(content), options=console.options)))


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

    def test_at_file_after_cjk_highlighted(self):
        result = render_at_and_skill_patterns(
            "请看@src/app.py",
            at_style="AT",
            skill_style="SKILL",
            other_style="OTHER",
        )
        assert get_spans_by_style(result, "AT") == ["@src/app.py"]

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

    def test_render_user_input_keeps_background_for_bash_mode(self):
        lines = rendered_segments("!pnpm lint [image /tmp/example.png]")

        expected_bg = Console(theme=get_theme().app_theme).get_style(ThemeKey.USER_INPUT.value).bgcolor
        content_segments = [segment for segment in lines[0][1:] if segment.text.strip()]

        assert content_segments
        assert all(segment.style is not None and segment.style.bgcolor == expected_bg for segment in content_segments)
