import tempfile
from base64 import b64decode
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from klaude_code.llm import image as image_module
from klaude_code.llm import input_common as input_common_module
from klaude_code.llm.anthropic.input import convert_history_to_input as anthropic_history
from klaude_code.llm.anthropic.input import convert_system_to_input as anthropic_system_input
from klaude_code.llm.google.input import convert_history_to_contents as google_history
from klaude_code.protocol.models import Usage

if TYPE_CHECKING:
    from klaude_code.protocol import message
from klaude_code.llm.openai_compatible.input import convert_history_to_input as openai_history
from klaude_code.llm.openai_responses.input import convert_history_to_input as responses_history
from klaude_code.llm.openrouter.input import convert_history_to_input as openrouter_history
from klaude_code.protocol import message

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


def test_anthropic_system_input_splits_static_and_dynamic_blocks() -> None:
    blocks = anthropic_system_input(
        "static\n\n__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__\n\ndynamic",
    )

    assert blocks == [
        {"type": "text", "text": "static", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "dynamic", "cache_control": {"type": "ephemeral"}},
    ]


def test_anthropic_history_keeps_frozen_user_images_stable_when_more_images_are_added(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_old = message.ImageURLPart(url=SAMPLE_DATA_URL, id="old", frozen=True)
    frozen_new = message.ImageURLPart(url=SAMPLE_DATA_URL, id="new", frozen=True)
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.TextPart(text="first"), frozen_old)),
        message.UserMessage(parts=_parts(message.TextPart(text="second"), frozen_new)),
    ]

    def _fail(_url: str, *, max_dimension: int = image_module.MAX_IMAGE_DIMENSION) -> str:
        raise AssertionError(
            f"normalize_image_data_url should not be called for frozen history images: {max_dimension}"
        )

    monkeypatch.setattr(image_module, "normalize_image_data_url", _fail)

    messages = anthropic_history(history, model_name=None)
    first = _ensure_dict(messages[0])
    first_blocks = _ensure_list(first["content"])
    first_image = _ensure_dict(first_blocks[1])
    assert _ensure_dict(first_image["source"])["data"] == SAMPLE_IMAGE_BASE64


def test_anthropic_history_keeps_frozen_file_images_stable_when_more_images_are_added(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "frozen.png"
    path.write_bytes(b64decode(SAMPLE_IMAGE_BASE64))
    frozen_file = message.ImageFilePart(file_path=str(path), mime_type="image/png", frozen=True)
    frozen_url = message.ImageURLPart(url=SAMPLE_DATA_URL, id="new", frozen=True)
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.TextPart(text="first"), frozen_file)),
        message.UserMessage(parts=_parts(message.TextPart(text="second"), frozen_url)),
    ]

    def _fail(_image_bytes: bytes, _mime_type: str, *, max_dimension: int = image_module.MAX_IMAGE_DIMENSION):
        raise AssertionError(f"frozen file history images should not be recompressed: {max_dimension}")

    monkeypatch.setattr(image_module, "_compress_image_bytes_for_request", _fail)

    messages = anthropic_history(history, model_name=None)
    first = _ensure_dict(messages[0])
    first_blocks = _ensure_list(first["content"])
    first_image = _ensure_dict(first_blocks[1])
    assert _ensure_dict(first_image["source"])["data"] == SAMPLE_IMAGE_BASE64


def test_anthropic_history_marks_missing_file_images(tmp_path: Path) -> None:
    missing = tmp_path / "missing.png"
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.ImageFilePart(file_path=str(missing), mime_type="image/png")))
    ]

    messages = anthropic_history(history, model_name=None)

    first = _ensure_dict(messages[0])
    first_blocks = _ensure_list(first["content"])
    placeholder = _ensure_dict(first_blocks[0])
    assert placeholder["type"] == "text"
    assert "image unavailable" in str(placeholder["text"])
    assert str(missing) in str(placeholder["text"])


def test_anthropic_history_omits_single_image_that_exceeds_inline_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(image_module, "_MAX_IMAGE_SIZE_BYTES", 100)
    monkeypatch.setattr(image_module, "_MAX_BASE64_IMAGE_SIZE_BYTES", 8)
    path = tmp_path / "too-large.png"
    path.write_bytes(b"not-really-a-png-but-large")
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.ImageFilePart(file_path=str(path), mime_type="image/png", frozen=True)))
    ]

    messages = anthropic_history(history, model_name=None)

    first = _ensure_dict(messages[0])
    first_blocks = _ensure_list(first["content"])
    placeholder = _ensure_dict(first_blocks[0])
    assert placeholder["type"] == "text"
    assert "single image size limit exceeded" in str(placeholder["text"])
    assert not any(_ensure_dict(block).get("type") == "image" for block in first_blocks)


def test_inline_image_budget_applies_across_provider_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    oversized_url = f"data:image/png;base64,{'A' * 1024}"
    history: list[message.Message] = [
        message.UserMessage(parts=[message.ImageURLPart(url=oversized_url, id=None)]),
    ]
    monkeypatch.setattr(input_common_module, "INLINE_IMAGE_PAYLOAD_BUDGET_BYTES", 10)

    openai_messages = openai_history(history, system=None, model_name=None)
    openai_content = _ensure_list(_ensure_dict(openai_messages[0])["content"])
    openai_text = _ensure_dict(openai_content[0])
    assert openai_text["type"] == "text"
    assert "image omitted from request" in str(openai_text["text"])

    openrouter_messages = openrouter_history(history, system=None, model_name=None)
    openrouter_content = _ensure_list(_ensure_dict(openrouter_messages[0])["content"])
    openrouter_text = _ensure_dict(openrouter_content[0])
    assert openrouter_text["type"] == "text"
    assert "image omitted from request" in str(openrouter_text["text"])

    responses_items = responses_history(history, model_name=None)
    responses_content = _ensure_list(_ensure_dict(responses_items[0])["content"])
    responses_text = _ensure_dict(responses_content[0])
    assert responses_text["type"] == "input_text"
    assert "image omitted from request" in str(responses_text["text"])

    google_contents = google_history(history, model_name=None)
    assert google_contents[0].parts is not None
    assert "image omitted from request" in str(google_contents[0].parts[0].text)


def test_anthropic_history_omits_old_tool_images_when_inline_payload_exceeds_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_data = "A" * 1024
    image_url = f"data:image/png;base64,{image_data}"
    history: list[message.Message] = [
        message.ToolResultMessage(
            call_id=f"tool-{idx}",
            tool_name="Read",
            status="success",
            output_text=f"[image] img-{idx}.png",
            parts=[message.ImageURLPart(url=image_url, id=None)],
        )
        for idx in range(3)
    ]
    monkeypatch.setattr(input_common_module, "INLINE_IMAGE_PAYLOAD_BUDGET_BYTES", 2500)

    messages = anthropic_history(history, model_name=None)

    tool_message = _ensure_dict(messages[0])
    tool_results = [_ensure_dict(block) for block in _ensure_list(tool_message["content"])]
    first_tool_content = _ensure_list(tool_results[0]["content"])
    first_tool_text = _ensure_dict(first_tool_content[0])
    assert "image omitted from request" in str(first_tool_text["text"])
    assert all(_ensure_dict(block).get("type") != "image" for block in first_tool_content)

    for tool_result in tool_results[1:]:
        content = [_ensure_dict(block) for block in _ensure_list(tool_result["content"])]
        assert any(block.get("type") == "image" for block in content)


def test_anthropic_history_keeps_contiguous_recent_tool_images_when_trimming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls = [
        f"data:image/png;base64,{'A' * 100}",
        f"data:image/png;base64,{'A' * 2000}",
        f"data:image/png;base64,{'A' * 1800}",
    ]
    history: list[message.Message] = [
        message.ToolResultMessage(
            call_id=f"tool-{idx}",
            tool_name="Read",
            status="success",
            output_text=f"[image] img-{idx}.png",
            parts=[message.ImageURLPart(url=url, id=None)],
        )
        for idx, url in enumerate(urls)
    ]
    monkeypatch.setattr(input_common_module, "INLINE_IMAGE_PAYLOAD_BUDGET_BYTES", 1900)

    messages = anthropic_history(history, model_name=None)

    tool_message = _ensure_dict(messages[0])
    tool_results = [_ensure_dict(block) for block in _ensure_list(tool_message["content"])]
    image_counts = []
    for tool_result in tool_results:
        content = [_ensure_dict(block) for block in _ensure_list(tool_result["content"])]
        image_counts.append(sum(1 for block in content if block.get("type") == "image"))
    assert image_counts == [0, 0, 1]


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

    # Tool message content stays as a string for generic chat-completions providers.
    tool_message = _ensure_dict(messages[1])
    assert tool_message["role"] == "tool"
    assert tool_message["content"] == "done"

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


def test_openrouter_history_ignores_assistant_images():
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
        assert "images" not in first


def test_openai_compatible_history_ignores_assistant_images():
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
        assert "images" not in first


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


def test_responses_history_function_call_output_can_be_string():
    history: list[message.Message] = [
        message.ToolResultMessage(
            call_id="tool-1",
            tool_name="Read",
            status="success",
            output_text="done",
        ),
    ]

    items = responses_history(
        history,
        model_name=None,
        function_call_output_string=True,
        include_input_status=True,
    )
    tool_item = _ensure_dict(items[0])
    assert tool_item["type"] == "function_call_output"
    assert tool_item["output"] == "done"
    assert tool_item["status"] == "completed"


def test_responses_history_assistant_and_reasoning_include_status_in_string_mode():
    history: list[message.Message] = [
        message.AssistantMessage(
            parts=_parts(
                message.ThinkingTextPart(text="reasoning"),
                message.TextPart(text="answer"),
            )
        ),
    ]

    items = responses_history(
        history,
        model_name=None,
        function_call_output_string=True,
        include_input_status=True,
    )
    reasoning_item = _ensure_dict(items[0])
    assert reasoning_item["type"] == "reasoning"
    assert reasoning_item["status"] == "completed"

    assistant_item = _ensure_dict(items[1])
    assert assistant_item["type"] == "message"
    assert assistant_item["role"] == "assistant"
    assert assistant_item["status"] == "completed"


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


def test_developer_message_with_prepend_marker_prepends_user_content_across_providers():
    history: list[message.Message] = [
        message.UserMessage(parts=_parts(message.TextPart(text="USER"))),
        message.DeveloperMessage(
            parts=_parts(message.TextPart(text="MEMORY")),
            attachment_position="prepend",
        ),
    ]

    anthropic_messages = anthropic_history(history, model_name=None)
    anth_user_content = _ensure_list(_ensure_dict(anthropic_messages[0])["content"])
    assert _ensure_dict(anth_user_content[0])["text"] == "MEMORY\n"
    assert _ensure_dict(anth_user_content[1])["text"] == "USER"

    openai_messages = openai_history(history, system=None, model_name=None)
    openai_user_content = _ensure_list(_ensure_dict(openai_messages[0])["content"])
    assert _ensure_dict(openai_user_content[0])["text"] == "MEMORY\n"
    assert _ensure_dict(openai_user_content[1])["text"] == "USER"

    openrouter_messages = openrouter_history(history, system=None, model_name=None)
    openrouter_user_content = _ensure_list(_ensure_dict(openrouter_messages[0])["content"])
    assert _ensure_dict(openrouter_user_content[0])["text"] == "MEMORY\n"
    assert _ensure_dict(openrouter_user_content[1])["text"] == "USER"

    responses_items = responses_history(history, model_name=None)
    responses_user_item = _ensure_dict(responses_items[0])
    responses_user_content = _ensure_list(responses_user_item["content"])
    assert _ensure_dict(responses_user_content[0])["text"] == "MEMORY\n"
    assert _ensure_dict(responses_user_content[1])["text"] == "USER"


def test_developer_message_with_prepend_marker_prepends_tool_output_across_providers():
    history: list[message.Message] = [
        message.ToolResultMessage(call_id="call-1", tool_name="Read", status="success", output_text="TOOL"),
        message.DeveloperMessage(
            parts=_parts(message.TextPart(text="MEMORY")),
            attachment_position="prepend",
        ),
    ]

    anthropic_messages = anthropic_history(history, model_name=None)
    anth_tool_message = _ensure_dict(anthropic_messages[0])
    anth_tool_entry = _ensure_dict(_ensure_list(anth_tool_message["content"])[0])
    anth_tool_blocks = _ensure_list(anth_tool_entry["content"])
    assert _ensure_dict(anth_tool_blocks[0])["text"] == "MEMORY\n\nTOOL"

    openai_messages = openai_history(history, system=None, model_name=None)
    assert _ensure_dict(openai_messages[0])["content"] == "MEMORY\n\nTOOL"

    openrouter_messages = openrouter_history(history, system=None, model_name=None)
    assert _ensure_dict(openrouter_messages[0])["content"] == "MEMORY\n\nTOOL"

    responses_items = responses_history(history, model_name=None)
    responses_tool_item = _ensure_dict(responses_items[0])
    responses_tool_output = _ensure_list(responses_tool_item["output"])
    assert _ensure_dict(responses_tool_output[0])["text"] == "MEMORY\n\nTOOL"


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
def usage_instances(draw: st.DrawFn) -> "Usage":
    """Generate Usage instances with valid token counts."""
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
def test_usage_total_tokens_computed_correctly(usage: "Usage") -> None:
    """Property: total_tokens = input_tokens + output_tokens."""
    assert usage.total_tokens == usage.input_tokens + usage.output_tokens


@given(usage=usage_instances())
@settings(max_examples=100, deadline=None)
def test_usage_total_cost_computed_correctly(usage: "Usage") -> None:
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
def test_usage_context_usage_percent_bounds(usage: "Usage") -> None:
    """Property: context_usage_percent is None or non-negative."""
    if usage.context_usage_percent is not None:
        assert usage.context_usage_percent >= 0
