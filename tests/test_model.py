import tempfile
from base64 import b64decode
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from hypothesis import given, settings
from hypothesis import strategies as st

from klaude_code.llm.anthropic.input import convert_history_to_input as anthropic_history

if TYPE_CHECKING:
    from klaude_code.protocol import message, model
from klaude_code.llm.openai_compatible.input import convert_history_to_input as openai_history
from klaude_code.llm.openai_responses.input import convert_history_to_input as responses_history
from klaude_code.llm.openrouter.input import convert_history_to_input as openrouter_history
from klaude_code.protocol import message, model

SAMPLE_IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
SAMPLE_DATA_URL = f"data:image/png;base64,{SAMPLE_IMAGE_BASE64}"


def _make_image_part() -> message.ImageURLPart:
    return message.ImageURLPart(url=SAMPLE_DATA_URL, id=None)


def _parts(*parts: message.Part) -> list[message.Part]:
    return list(parts)


def _ensure_dict(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _ensure_list(value: object) -> list[Any]:
    assert isinstance(value, list)
    return cast(list[Any], value)


def test_anthropic_history_includes_image_blocks():
    image_part = _make_image_part()
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.TextPart(text="See"), image_part)),
        message.ToolResultMessage(
            call_id="tool-1",
            tool_name="Read",
            status="success",
            output_text="done",
            parts=_parts(image_part),
        ),
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
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.TextPart(text="See"), image_part)),
        message.ToolResultMessage(
            call_id="tool-1",
            tool_name="Read",
            status="success",
            output_text="done",
            parts=_parts(image_part),
        ),
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

    # Tool message content is a list (required by openrouter cache control)
    tool_message = _ensure_dict(messages[1])
    assert tool_message["role"] == "tool"
    tool_content = _ensure_list(tool_message["content"])
    assert len(tool_content) == 1
    assert _ensure_dict(tool_content[0]) == {"type": "text", "text": "done"}

    # Images from tool result are sent as a separate user message
    image_user_msg = _ensure_dict(messages[2])
    assert image_user_msg["role"] == "user"
    image_content = _ensure_list(image_user_msg["content"])
    assert len(image_content) == 2
    assert _ensure_dict(image_content[0])["type"] == "text"
    image_block = _ensure_dict(image_content[1])
    assert image_block["type"] == "image_url"
    assert _ensure_dict(image_block["image_url"])["url"] == SAMPLE_DATA_URL


def test_openrouter_history_includes_image_url_parts():
    image_part = _make_image_part()
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.TextPart(text="See"), image_part)),
        message.ToolResultMessage(
            call_id="tool-1",
            tool_name="Read",
            status="success",
            output_text="done",
            parts=_parts(image_part),
        ),
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

        assistant_image = message.ImageFilePart(file_path=str(img_path), mime_type="image/png")
        history: list[message.Message] = [
            message.AssistantMessage(parts=_parts(message.TextPart(text="Here"), assistant_image)),
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

        assistant_image = message.ImageFilePart(file_path=str(img_path), mime_type="image/png")
        history: list[message.Message] = [
            message.AssistantMessage(parts=_parts(message.TextPart(text="Here"), assistant_image)),
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
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.TextPart(text="See"), image_part)),
        message.ToolResultMessage(
            call_id="tool-1",
            tool_name="Read",
            status="success",
            output_text="done",
            parts=_parts(image_part),
        ),
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
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.TextPart(text="See"))),
        message.DeveloperMessage(parts=_parts(message.TextPart(text="Reminder"), image_part)),
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
    user_item = _ensure_dict(responses_items[0])
    assert user_item["role"] == "user"
    user_parts = _ensure_list(user_item["content"])
    assert _ensure_dict(user_parts[1])["type"] == "input_text"
    assert _ensure_dict(user_parts[2])["type"] == "input_image"


def test_anthropic_tool_group_includes_developer_images():
    image_part = _make_image_part()
    history: list[message.Message] = [
        message.ToolResultMessage(
            call_id="tool-1",
            tool_name="Read",
            status="success",
            output_text="done",
        ),
        message.DeveloperMessage(parts=_parts(message.TextPart(text="Reminder"), image_part)),
    ]

    messages = anthropic_history(history, model_name=None)
    tool_message = _ensure_dict(messages[0])
    tool_entry = _ensure_dict(_ensure_list(tool_message["content"])[0])
    tool_blocks = _ensure_list(tool_entry["content"])
    assert _ensure_dict(tool_blocks[-1])["type"] == "image"


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
