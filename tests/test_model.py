import sys
from pathlib import Path

# Ensure we can import from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# noqa: E402
from codex_mini.protocol import model  # noqa: E402
from codex_mini.protocol.model import group_response_items_gen  # noqa: E402


def test_group_response_items_gen():
    # Create test item variables for different types
    user_item = model.UserMessageItem(content="User message")
    assistant_item = model.AssistantMessageItem(content="Assistant message")
    developer_item = model.DeveloperMessageItem(content="Developer message")
    reasoning_item = model.ReasoningItem(content="Reasoning", model="gpt-5")
    tool_call_item = model.ToolCallItem(call_id="call_1", name="test_tool", arguments="{}")
    tool_result_item = model.ToolResultItem(call_id="call_1", output="result", status="success")
    start_item = model.StartItem(response_id="resp_1")
    metadata_item = model.ResponseMetadataItem(response_id="resp_1")

    # Test case 1: Simple consecutive user messages
    input_1 = [user_item, user_item, user_item]
    expected_1 = [("user", [user_item, user_item, user_item])]
    result_1 = list(group_response_items_gen(input_1))
    assert result_1 == expected_1

    # Test case 2: Simple consecutive assistant messages
    input_2 = [assistant_item, reasoning_item, tool_call_item]
    expected_2 = [("assistant", [assistant_item, reasoning_item, tool_call_item])]
    result_2 = list(group_response_items_gen(input_2))
    assert result_2 == expected_2

    # Test case 3: Tool result item as single group
    input_3 = [tool_result_item]
    expected_3 = [("tool", [tool_result_item])]
    result_3 = list(group_response_items_gen(input_3))
    assert result_3 == expected_3

    # Test case 4: Mixed types with group switching
    input_4 = [user_item, user_item, assistant_item, reasoning_item]
    expected_4 = [("user", [user_item, user_item]), ("assistant", [assistant_item, reasoning_item])]
    result_4 = list(group_response_items_gen(input_4))
    assert result_4 == expected_4

    # Test case 5: Developer message attaches to previous group
    input_5 = [user_item, developer_item]
    expected_5 = [("user", [user_item, developer_item])]
    result_5 = list(group_response_items_gen(input_5))
    assert result_5 == expected_5

    # Test case 6: Tool result interrupts and creates single group
    input_6 = [user_item, tool_result_item, assistant_item]
    expected_6 = [("user", [user_item]), ("tool", [tool_result_item]), ("assistant", [assistant_item])]
    result_6 = list(group_response_items_gen(input_6))
    assert result_6 == expected_6

    # Test case 7: Complex scenario with all types
    input_7 = [
        user_item,
        user_item,
        developer_item,
        assistant_item,
        reasoning_item,
        tool_call_item,
        tool_result_item,
        user_item,
    ]
    expected_7 = [
        ("user", [user_item, user_item, developer_item]),
        ("assistant", [assistant_item, reasoning_item, tool_call_item]),
        ("tool", [tool_result_item]),
        ("user", [user_item]),
    ]
    result_7 = list(group_response_items_gen(input_7))
    assert result_7 == expected_7

    # Test case 8: "other" items are filtered out
    input_8 = [start_item, user_item, metadata_item, assistant_item]
    expected_8 = [("user", [user_item]), ("assistant", [assistant_item])]
    result_8 = list(group_response_items_gen(input_8))
    assert result_8 == expected_8

    # Test case 9: Empty input
    input_9: list[model.ConversationItem] = []
    expected_9 = []
    result_9 = list(group_response_items_gen(input_9))
    assert result_9 == expected_9

    # Test case 10: Only "other" items
    input_10 = [start_item, metadata_item]
    expected_10 = []
    result_10 = list(group_response_items_gen(input_10))
    assert result_10 == expected_10


if __name__ == "__main__":
    test_group_response_items_gen()
    print("All tests passed!")
