import io

from rich.console import Console

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import SubAgentState
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.sub_agent import render_sub_agent_call, render_sub_agent_result
from klaude_code.tui.components.tools import SUB_AGENT_FULL_TOOL_RESULT_MAX_LINES
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail


def _render(renderable: object, *, width: int = 100) -> str:
    output = io.StringIO()
    Console(file=output, width=width, force_terminal=False, theme=get_theme().app_theme).print(renderable)
    return output.getvalue()


def test_full_sub_agent_prompt_and_result_keep_all_lines() -> None:
    prompt = "\n".join(f"prompt line {index}" for index in range(25))
    result = "\n".join(f"result line {index}" for index in range(15))
    state = SubAgentState(
        sub_agent_type="finder",
        sub_agent_desc="searching",
        sub_agent_prompt=prompt,
    )

    full_call = _render(render_sub_agent_call(state))
    full_result = _render(render_sub_agent_result(result))

    assert "prompt line 24" in full_call
    assert "more" not in full_call
    assert "result line 14" in full_result
    assert "more" not in full_result


def test_full_sub_agent_error_keeps_configured_lines() -> None:
    renderer = TUICommandRenderer()
    renderer.set_transcript_detail(Detail.FULL)
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)
    total_lines = SUB_AGENT_FULL_TOOL_RESULT_MAX_LINES + 10
    head_count = SUB_AGENT_FULL_TOOL_RESULT_MAX_LINES // 2
    tail_start = total_lines - (SUB_AGENT_FULL_TOOL_RESULT_MAX_LINES - head_count)
    result = "\n".join(f"error line {index}" for index in range(total_lines))
    event = events.ToolResultEvent(
        session_id="sub-1",
        tool_call_id="bash-1",
        tool_name=tools.BASH,
        result=result,
        status="error",
    )

    assert renderer.display_tool_call_result(event, is_sub_agent=True) is True

    rendered = output.getvalue()
    assert "error line 0" in rendered
    assert f"error line {head_count - 1}" in rendered
    assert f"error line {head_count}" not in rendered
    assert f"error line {tail_start - 1}" not in rendered
    assert f"error line {tail_start}" in rendered
    assert f"error line {total_lines - 1}" in rendered
    assert "… (more 10 lines)" in rendered


def test_full_sub_agent_tool_result_keeps_configured_lines_with_head_and_tail() -> None:
    renderer = TUICommandRenderer()
    renderer.set_transcript_detail(Detail.FULL)
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    total_lines = SUB_AGENT_FULL_TOOL_RESULT_MAX_LINES + 10
    head_count = SUB_AGENT_FULL_TOOL_RESULT_MAX_LINES // 2
    tail_start = total_lines - (SUB_AGENT_FULL_TOOL_RESULT_MAX_LINES - head_count)
    result = "\n".join(f"line-{index}" for index in range(total_lines))
    event = events.ToolResultEvent(
        session_id="sub-1",
        tool_call_id="bash-1",
        tool_name=tools.BASH,
        result=result,
        status="success",
    )

    assert renderer.display_tool_call_result(event, is_sub_agent=True) is True

    rendered = output.getvalue()
    assert f"line-{head_count - 1}" in rendered
    assert f"line-{head_count}" not in rendered
    assert f"line-{tail_start - 1}" not in rendered
    assert f"line-{tail_start}" in rendered
    assert f"line-{total_lines - 1}" in rendered
    assert "… (more 10 lines)" in rendered
