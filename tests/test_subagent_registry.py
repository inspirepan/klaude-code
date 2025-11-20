import codex_mini.core.tool as core_tool  # noqa: F401
from codex_mini.config.config import get_example_config
from codex_mini.core.subagent import is_sub_agent_tool, sub_agent_tool_names
from codex_mini.core.tool.tool_registry import get_main_agent_tools, get_sub_agent_tools
from codex_mini.protocol import tools


def test_subagent_models_present_in_example() -> None:
    cfg = get_example_config()
    assert cfg.subagent_models["Explore"] == "sonnet-4"


def test_sub_agent_tool_visibility_respects_filters() -> None:
    gpt5_tools = set(sub_agent_tool_names(enabled_only=True, model_name="gpt-5"))
    claude_tools = set(sub_agent_tool_names(enabled_only=True, model_name="claude-3"))

    assert tools.ORACLE not in gpt5_tools
    assert tools.ORACLE in claude_tools


def test_main_agent_tools_include_registered_sub_agents() -> None:
    assert core_tool is not None  # ensure tool registry side-effects executed
    gpt5_tool_names = {schema.name for schema in get_main_agent_tools("gpt-5")}
    claude_tool_names = {schema.name for schema in get_main_agent_tools("claude-3")}

    assert tools.TASK in gpt5_tool_names
    assert tools.EXPLORE in gpt5_tool_names
    assert tools.ORACLE not in gpt5_tool_names

    assert {tools.TASK, tools.EXPLORE, tools.ORACLE}.issubset(claude_tool_names)


def test_get_sub_agent_tools_uses_profile_tool_set() -> None:
    explore_tools = {schema.name for schema in get_sub_agent_tools("sonnet-4", tools.SubAgentType.EXPLORE)}
    oracle_tools_for_gpt5 = get_sub_agent_tools("gpt-5", tools.SubAgentType.ORACLE)

    assert explore_tools == {tools.BASH, tools.READ}
    assert oracle_tools_for_gpt5 == []
    assert is_sub_agent_tool(tools.EXPLORE)
