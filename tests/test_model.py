from typing import Any, cast

from codex_mini.llm.anthropic.input import convert_history_to_input as anthropic_history
from codex_mini.llm.openai_compatible.input import convert_history_to_input as openai_history
from codex_mini.llm.openrouter.input import convert_history_to_input as openrouter_history
from codex_mini.llm.responses.input import convert_history_to_input as responses_history
from codex_mini.protocol import model
from codex_mini.protocol.model import group_response_items_gen

SAMPLE_IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
SAMPLE_DATA_URL = f"data:image/png;base64,{SAMPLE_IMAGE_BASE64}"


def test_group_response_items_gen():
    # Create test item variables for different types
    user_item = model.UserMessageItem(content="User message")
    assistant_item = model.AssistantMessageItem(content="Assistant message")
    developer_item = model.DeveloperMessageItem(content="Developer message")
    reasoning_item = model.ReasoningTextItem(content="Reasoning")
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


def _make_image_part() -> model.ImageURLPart:
    return model.ImageURLPart(image_url=model.ImageURLPart.ImageURL(url=SAMPLE_DATA_URL, id=None))


def _ensure_dict(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _ensure_list(value: object) -> list[Any]:
    assert isinstance(value, list)
    return cast(list[Any], value)


def test_anthropic_history_includes_image_blocks():
    image_part = _make_image_part()
    history: list[model.ConversationItem] = [
        model.UserMessageItem(content="See", images=[image_part]),
        model.ToolResultItem(call_id="tool-1", output="done", status="success", images=[image_part]),
    ]

    messages = anthropic_history(history, model_name=None)
    first = _ensure_dict(messages[0])
    assert first["role"] == "user"
    user_blocks = _ensure_list(first["content"])
    user_block_first = _ensure_dict(user_blocks[0])
    assert user_block_first["type"] == "text"
    second_block = _ensure_dict(user_blocks[1])
    assert second_block["type"] == "image"
    source = _ensure_dict(second_block["source"])
    assert source["type"] == "base64"

    tool_message = _ensure_dict(messages[1])
    tool_contents = _ensure_list(tool_message["content"])
    tool_entry = _ensure_dict(tool_contents[0])
    assert tool_entry["type"] == "tool_result"
    tool_blocks = _ensure_list(tool_entry["content"])
    first_tool_block = _ensure_dict(tool_blocks[0])
    assert first_tool_block["type"] == "text"
    second_tool_block = _ensure_dict(tool_blocks[1])
    assert second_tool_block["type"] == "image"


def test_openai_compatible_history_includes_image_url_parts():
    image_part = _make_image_part()
    history: list[model.ConversationItem] = [
        model.UserMessageItem(content="See", images=[image_part]),
        model.ToolResultItem(call_id="tool-1", output="done", status="success", images=[image_part]),
    ]

    messages = openai_history(history, system=None, model_name=None)
    first = _ensure_dict(messages[0])
    assert first["role"] == "user"
    user_content = _ensure_list(first["content"])
    first_part = _ensure_dict(user_content[0])
    assert first_part["type"] == "text"
    second_part = _ensure_dict(user_content[1])
    assert second_part["type"] == "image_url"
    image_url = _ensure_dict(second_part["image_url"])
    assert image_url["url"] == SAMPLE_DATA_URL

    tool_message = _ensure_dict(messages[1])
    assert tool_message["role"] == "tool"
    content = tool_message["content"]
    assert isinstance(content, list)
    tool_blocks = cast(list[Any], content)
    first_block = _ensure_dict(tool_blocks[0])
    assert first_block["type"] == "text"


def test_openrouter_history_includes_image_url_parts():
    image_part = _make_image_part()
    history: list[model.ConversationItem] = [
        model.UserMessageItem(content="See", images=[image_part]),
        model.ToolResultItem(call_id="tool-1", output="done", status="success", images=[image_part]),
    ]

    messages = openrouter_history(history, system=None, model_name=None)
    first = _ensure_dict(messages[0])
    assert first["role"] == "user"
    user_content = _ensure_list(first["content"])
    assert _ensure_dict(user_content[0])["type"] == "text"
    second_part = _ensure_dict(user_content[1])
    assert second_part["type"] == "image_url"
    image_url = _ensure_dict(second_part["image_url"])
    assert image_url["url"] == SAMPLE_DATA_URL


def test_responses_history_includes_image_inputs():
    image_part = _make_image_part()
    history: list[model.ConversationItem] = [
        model.UserMessageItem(content="See", images=[image_part]),
        model.ToolResultItem(call_id="tool-1", output="done", status="success", images=[image_part]),
    ]

    items = responses_history(history, model_name=None)
    first_item = _ensure_dict(items[0])
    assert first_item["type"] == "message"
    user_parts = _ensure_list(first_item.get("content"))
    user_text_part = _ensure_dict(user_parts[0])
    assert user_text_part["type"] == "input_text"
    user_image_part = _ensure_dict(user_parts[1])
    assert user_image_part["type"] == "input_image"
    assert user_image_part.get("image_url") == SAMPLE_DATA_URL

    tool_item = _ensure_dict(items[1])
    assert tool_item["type"] == "function_call_output"
    tool_parts = _ensure_list(tool_item.get("output"))
    first_tool_part = _ensure_dict(tool_parts[0])
    assert first_tool_part["type"] == "input_text"
    second_tool_part = _ensure_dict(tool_parts[1])
    assert second_tool_part["type"] == "input_image"


def test_developer_message_images_propagate_to_user_group():
    image_part = _make_image_part()
    history: list[model.ConversationItem] = [
        model.UserMessageItem(content="See"),
        model.DeveloperMessageItem(content="Reminder", images=[image_part]),
    ]

    anthropic_messages = anthropic_history(history, model_name=None)
    user_content = _ensure_list(_ensure_dict(anthropic_messages[0])["content"])
    assert _ensure_dict(user_content[1])["type"] == "text"
    assert "Reminder" in _ensure_dict(user_content[1])["text"]
    assert _ensure_dict(user_content[2])["type"] == "image"

    openai_messages = openai_history(history, system=None, model_name=None)
    openai_parts = _ensure_list(_ensure_dict(openai_messages[0])["content"])
    assert _ensure_dict(openai_parts[1])["type"] == "text"
    assert _ensure_dict(openai_parts[2])["type"] == "image_url"

    responses_items = responses_history(history, model_name=None)
    developer_item = _ensure_dict(responses_items[1])
    assert developer_item["role"] == "user"  # GPT-5 series do not support image in "developer" role
    developer_parts = _ensure_list(developer_item["content"])
    assert _ensure_dict(developer_parts[0])["type"] == "input_text"
    assert _ensure_dict(developer_parts[1])["type"] == "input_image"


def test_anthropic_tool_group_includes_developer_images():
    image_part = _make_image_part()
    history: list[model.ConversationItem] = [
        model.ToolResultItem(call_id="tool-1", output="done", status="success"),
        model.DeveloperMessageItem(content="Reminder", images=[image_part]),
    ]

    messages = anthropic_history(history, model_name=None)
    tool_message = _ensure_dict(messages[0])
    tool_entry = _ensure_dict(_ensure_list(tool_message["content"])[0])
    tool_blocks = _ensure_list(tool_entry["content"])
    assert _ensure_dict(tool_blocks[-1])["type"] == "image"


if __name__ == "__main__":
    test_group_response_items_gen()
    print("All tests passed!")
