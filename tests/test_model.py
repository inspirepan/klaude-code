from codex_mini.protocol import model
from codex_mini.protocol.model import group_response_items_gen


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

    # Test case 11: ToolResult followed by Developer attaches to same tool group
    input_11 = [tool_result_item, developer_item]
    expected_11 = [("tool", [tool_result_item, developer_item])]
    result_11 = list(group_response_items_gen(input_11))
    assert result_11 == expected_11

    # Test case 12: Multiple Developers attach to the same preceding ToolResult
    input_12 = [tool_result_item, developer_item, developer_item]
    expected_12 = [("tool", [tool_result_item, developer_item, developer_item])]
    result_12 = list(group_response_items_gen(input_12))
    assert result_12 == expected_12

    # Test case 13: Developer alone is dropped
    input_13 = [developer_item]
    expected_13: list[tuple[str, list[model.ConversationItem]]] = []
    result_13 = list(group_response_items_gen(input_13))
    assert result_13 == expected_13

    # Test case 14: Assistant then Developer then Assistant merges (developer dropped)
    input_14 = [assistant_item, developer_item, assistant_item]
    expected_14 = [("assistant", [assistant_item, assistant_item])]
    result_14 = list(group_response_items_gen(input_14))
    assert result_14 == expected_14

    # Test case 15: Consecutive ToolResults produce separate tool groups
    input_15 = [tool_result_item, tool_result_item]
    expected_15 = [("tool", [tool_result_item]), ("tool", [tool_result_item])]
    result_15 = list(group_response_items_gen(input_15))
    assert result_15 == expected_15

    # Test case 16: ToolResult then Developer then User -> developer attaches to tool, then user as new group
    input_16 = [tool_result_item, developer_item, user_item]
    expected_16 = [("tool", [tool_result_item, developer_item]), ("user", [user_item])]
    result_16 = list(group_response_items_gen(input_16))
    assert result_16 == expected_16

    # Test case 17: ToolResult, StartItem (other), Developer -> developer still attaches to preceding tool group
    input_17 = [tool_result_item, start_item, developer_item]
    expected_17 = [("tool", [tool_result_item, developer_item])]
    result_17 = list(group_response_items_gen(input_17))
    assert result_17 == expected_17

    # Test case 18: ToolResult then Developer then ToolResult -> first tool group carries developer, second is standalone
    input_18 = [tool_result_item, developer_item, tool_result_item]
    expected_18 = [("tool", [tool_result_item, developer_item]), ("tool", [tool_result_item])]
    result_18 = list(group_response_items_gen(input_18))
    assert result_18 == expected_18

    # Test case 19: Developer after assistant at end is dropped, assistant still flushed
    input_19 = [assistant_item, developer_item]
    expected_19 = [("assistant", [assistant_item])]
    result_19 = list(group_response_items_gen(input_19))
    assert result_19 == expected_19


if __name__ == "__main__":
    test_group_response_items_gen()
    print("All tests passed!")
