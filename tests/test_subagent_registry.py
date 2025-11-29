import klaude_code.core.tool as core_tool  # noqa: F401
from klaude_code.core.sub_agent import sub_agent_tool_names
from klaude_code.core.tool import get_main_agent_tools


def test_sub_agent_tool_visibility_respects_filters() -> None:
    gpt5_tools = set(sub_agent_tool_names(enabled_only=True, model_name="gpt-5"))
    claude_tools = set(sub_agent_tool_names(enabled_only=True, model_name="claude-3"))

    assert "Oracle" not in gpt5_tools
    assert "Oracle" in claude_tools


def test_main_agent_tools_include_registered_sub_agents() -> None:
    assert core_tool is not None  # ensure tool registry side-effects executed
    gpt5_tool_names = {schema.name for schema in get_main_agent_tools("gpt-5")}
    claude_tool_names = {schema.name for schema in get_main_agent_tools("claude-3")}

    assert "Task" in gpt5_tool_names
    assert "Explore" in gpt5_tool_names
    assert "Oracle" not in gpt5_tool_names

    assert {"Task", "Explore", "Oracle"}.issubset(claude_tool_names)
