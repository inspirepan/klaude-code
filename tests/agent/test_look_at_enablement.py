import klaude_code.tool as core_tool
from klaude_code.agent.agent_profile import load_agent_tools
from klaude_code.protocol import tools


def test_look_at_added_for_non_vision_main_agent() -> None:
    assert core_tool is not None  # ensure tool registry side-effects executed
    names = [schema.name for schema in load_agent_tools("deepseek-v4-pro", supports_vision=False)]
    assert tools.LOOK_AT in names
    assert tools.READ in names


def test_look_at_absent_for_vision_main_agent() -> None:
    names = [schema.name for schema in load_agent_tools("claude-3")]
    assert tools.LOOK_AT not in names


def test_look_at_added_for_non_vision_sub_agent_profile() -> None:
    names = [schema.name for schema in load_agent_tools("deepseek-v4-pro", "general-purpose", supports_vision=False)]
    assert tools.LOOK_AT in names

    vision_names = [schema.name for schema in load_agent_tools("claude-3", "general-purpose")]
    assert tools.LOOK_AT not in vision_names
