import tempfile
from base64 import b64decode
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from hypothesis import given, settings
from hypothesis import strategies as st

from klaude_code.llm.anthropic.input import convert_history_to_input as anthropic_history

if TYPE_CHECKING:
    from klaude_code.protocol import model
from klaude_code.llm.input_common import GroupKind, group_response_items_gen
from klaude_code.llm.openai_compatible.input import convert_history_to_input as openai_history
from klaude_code.llm.openrouter.input import convert_history_to_input as openrouter_history
from klaude_code.llm.responses.input import convert_history_to_input as responses_history
from klaude_code.protocol import model

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
    expected_1 = [(GroupKind.USER, [user_item, user_item, user_item])]
    result_1 = list(group_response_items_gen(input_1))
    assert result_1 == expected_1

    # Test case 2: Simple consecutive assistant messages
    input_2 = [assistant_item, reasoning_item, tool_call_item]
    expected_2 = [(GroupKind.ASSISTANT, [assistant_item, reasoning_item, tool_call_item])]
    result_2 = list(group_response_items_gen(input_2))
    assert result_2 == expected_2

    # Test case 3: Tool result item as single group
    input_3 = [tool_result_item]
    expected_3 = [(GroupKind.TOOL, [tool_result_item])]
    result_3 = list(group_response_items_gen(input_3))
    assert result_3 == expected_3

    # Test case 4: Mixed types with group switching
    input_4 = [user_item, user_item, assistant_item, reasoning_item]
    expected_4 = [
        (GroupKind.USER, [user_item, user_item]),
        (GroupKind.ASSISTANT, [assistant_item, reasoning_item]),
    ]
    result_4 = list(group_response_items_gen(input_4))
    assert result_4 == expected_4

    # Test case 5: Developer message attaches to previous group
    input_5 = [user_item, developer_item]
    expected_5 = [(GroupKind.USER, [user_item, developer_item])]
    result_5 = list(group_response_items_gen(input_5))
    assert result_5 == expected_5

    # Test case 6: Tool result interrupts and creates single group
    input_6 = [user_item, tool_result_item, assistant_item]
    expected_6 = [
        (GroupKind.USER, [user_item]),
        (GroupKind.TOOL, [tool_result_item]),
        (GroupKind.ASSISTANT, [assistant_item]),
    ]
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
        (GroupKind.USER, [user_item, user_item, developer_item]),
        (GroupKind.ASSISTANT, [assistant_item, reasoning_item, tool_call_item]),
        (GroupKind.TOOL, [tool_result_item]),
        (GroupKind.USER, [user_item]),
    ]
    result_7 = list(group_response_items_gen(input_7))
    assert result_7 == expected_7

    # Test case 8: "other" items are filtered out
    input_8 = [start_item, user_item, metadata_item, assistant_item]
    expected_8 = [
        (GroupKind.USER, [user_item]),
        (GroupKind.ASSISTANT, [assistant_item]),
    ]
    result_8 = list(group_response_items_gen(input_8))
    assert result_8 == expected_8

    # Test case 9: Empty input
    input_9: list[model.ConversationItem] = []
    expected_9: list[tuple[GroupKind, list[model.ConversationItem]]] = []
    result_9 = list(group_response_items_gen(input_9))
    assert result_9 == expected_9

    # Test case 10: Only "other" items
    input_10 = [start_item, metadata_item]
    expected_10: list[tuple[GroupKind, list[model.ConversationItem]]] = []
    result_10 = list(group_response_items_gen(input_10))
    assert result_10 == expected_10

    # Test case 11: ToolResult followed by Developer attaches to same tool group
    input_11 = [tool_result_item, developer_item]
    expected_11 = [(GroupKind.TOOL, [tool_result_item, developer_item])]
    result_11 = list(group_response_items_gen(input_11))
    assert result_11 == expected_11

    # Test case 12: Multiple Developers attach to the same preceding ToolResult
    input_12 = [tool_result_item, developer_item, developer_item]
    expected_12 = [(GroupKind.TOOL, [tool_result_item, developer_item, developer_item])]
    result_12 = list(group_response_items_gen(input_12))
    assert result_12 == expected_12

    # Test case 13: Developer alone is dropped
    input_13 = [developer_item]
    expected_13: list[tuple[GroupKind, list[model.ConversationItem]]] = []
    result_13 = list(group_response_items_gen(input_13))
    assert result_13 == expected_13

    # Test case 14: Assistant then Developer then Assistant merges (developer dropped)
    input_14 = [assistant_item, developer_item, assistant_item]
    expected_14 = [(GroupKind.ASSISTANT, [assistant_item, assistant_item])]
    result_14 = list(group_response_items_gen(input_14))
    assert result_14 == expected_14

    # Test case 15: Consecutive ToolResults produce separate tool groups
    input_15 = [tool_result_item, tool_result_item]
    expected_15 = [
        (GroupKind.TOOL, [tool_result_item]),
        (GroupKind.TOOL, [tool_result_item]),
    ]
    result_15 = list(group_response_items_gen(input_15))
    assert result_15 == expected_15

    # Test case 16: ToolResult then Developer then User -> developer attaches to tool, then user as new group
    input_16 = [tool_result_item, developer_item, user_item]
    expected_16 = [
        (GroupKind.TOOL, [tool_result_item, developer_item]),
        (GroupKind.USER, [user_item]),
    ]
    result_16 = list(group_response_items_gen(input_16))
    assert result_16 == expected_16

    # Test case 17: ToolResult, StartItem (other), Developer -> developer still attaches to preceding tool group
    input_17 = [tool_result_item, start_item, developer_item]
    expected_17 = [(GroupKind.TOOL, [tool_result_item, developer_item])]
    result_17 = list(group_response_items_gen(input_17))
    assert result_17 == expected_17

    # Test case 18: ToolResult then Developer then ToolResult -> first tool group carries developer, second is standalone
    input_18 = [tool_result_item, developer_item, tool_result_item]
    expected_18 = [
        (GroupKind.TOOL, [tool_result_item, developer_item]),
        (GroupKind.TOOL, [tool_result_item]),
    ]
    result_18 = list(group_response_items_gen(input_18))
    assert result_18 == expected_18

    # Test case 19: Developer after assistant at end is dropped, assistant still flushed
    input_19 = [assistant_item, developer_item]
    expected_19 = [(GroupKind.ASSISTANT, [assistant_item])]
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


def test_openrouter_history_includes_assistant_images_for_multi_turn_editing():
    with tempfile.TemporaryDirectory() as tmpdir:
        img_path = Path(tmpdir) / "assistant.png"
        img_bytes = b64decode(SAMPLE_IMAGE_BASE64)
        img_path.write_bytes(img_bytes)

        assistant_image = model.AssistantImage(file_path=str(img_path), mime_type="image/png")
        history: list[model.ConversationItem] = [
            model.AssistantMessageItem(content="Here", images=[assistant_image]),
        ]

        messages = openrouter_history(history, system=None, model_name=None)
        first = _ensure_dict(messages[0])
        assert first["role"] == "assistant"
        images = _ensure_list(first["images"])
        first_image = _ensure_dict(images[0])
        image_url = _ensure_dict(first_image["image_url"])
        assert image_url["url"] == SAMPLE_DATA_URL


def test_openai_compatible_history_includes_assistant_images_for_multi_turn_editing():
    with tempfile.TemporaryDirectory() as tmpdir:
        img_path = Path(tmpdir) / "assistant.png"
        img_bytes = b64decode(SAMPLE_IMAGE_BASE64)
        img_path.write_bytes(img_bytes)

        assistant_image = model.AssistantImage(file_path=str(img_path), mime_type="image/png")
        history: list[model.ConversationItem] = [
            model.AssistantMessageItem(content="Here", images=[assistant_image]),
        ]

        messages = openai_history(history, system=None, model_name=None)
        first = _ensure_dict(messages[0])
        assert first["role"] == "assistant"
        images = _ensure_list(first["images"])
        first_image = _ensure_dict(images[0])
        image_url = _ensure_dict(first_image["image_url"])
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


# ============================================================================
# Property-based tests for Usage model
# ============================================================================


@st.composite
def usage_instances(draw: st.DrawFn) -> "model.Usage":
    """Generate Usage instances with valid token counts."""
    from klaude_code.protocol.model import Usage

    input_tokens = draw(st.integers(min_value=0, max_value=1_000_000))
    cached_tokens = draw(st.integers(min_value=0, max_value=input_tokens))
    output_tokens = draw(st.integers(min_value=0, max_value=1_000_000))
    reasoning_tokens = draw(st.integers(min_value=0, max_value=output_tokens))

    context_limit = draw(st.none() | st.integers(min_value=1, max_value=1_000_000))
    max_tokens = draw(st.none() | st.integers(min_value=1, max_value=100_000))
    context_size = draw(st.none() | st.integers(min_value=0, max_value=1_000_000))

    input_cost = draw(st.none() | st.floats(min_value=0, max_value=100, allow_nan=False))
    output_cost = draw(st.none() | st.floats(min_value=0, max_value=100, allow_nan=False))
    cache_read_cost = draw(st.none() | st.floats(min_value=0, max_value=100, allow_nan=False))

    return Usage(
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        context_limit=context_limit,
        max_tokens=max_tokens,
        context_size=context_size,
        input_cost=input_cost,
        output_cost=output_cost,
        cache_read_cost=cache_read_cost,
    )


@given(usage=usage_instances())
@settings(max_examples=100, deadline=None)
def test_usage_total_tokens_computed_correctly(usage: "model.Usage") -> None:
    """Property: total_tokens = input_tokens + output_tokens."""
    assert usage.total_tokens == usage.input_tokens + usage.output_tokens


@given(usage=usage_instances())
@settings(max_examples=100, deadline=None)
def test_usage_total_cost_computed_correctly(usage: "model.Usage") -> None:
    """Property: total_cost = sum of non-None cost components."""
    costs = [usage.input_cost, usage.output_cost, usage.cache_read_cost]
    non_none = [c for c in costs if c is not None]

    if non_none:
        assert usage.total_cost is not None
        assert abs(usage.total_cost - sum(non_none)) < 1e-9
    else:
        assert usage.total_cost is None


@given(usage=usage_instances())
@settings(max_examples=100, deadline=None)
def test_usage_context_usage_percent_bounds(usage: "model.Usage") -> None:
    """Property: context_usage_percent is None or non-negative."""
    if usage.context_usage_percent is not None:
        assert usage.context_usage_percent >= 0
