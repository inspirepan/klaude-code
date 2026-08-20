from klaude_code.llm.input_common import (
    apply_config_defaults,
    strip_images_for_text_only_model,
)
from klaude_code.protocol import llm_param, message


def _image_file_part() -> message.ImageFilePart:
    return message.ImageFilePart(file_path="/tmp/shot.png", mime_type="image/png", byte_size=100)


def _config(*, supports_vision: bool) -> llm_param.LLMConfigParameter:
    return llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.ANTHROPIC,
        model_id="test-model",
        supports_vision=supports_vision,
    )


def test_user_message_image_becomes_text_placeholder() -> None:
    original = message.UserMessage(parts=[message.TextPart(text="look"), _image_file_part()])

    stripped = strip_images_for_text_only_model([original])

    assert len(stripped) == 1
    parts = stripped[0].parts
    assert len(parts) == 2
    assert isinstance(parts[0], message.TextPart) and parts[0].text == "look"
    assert isinstance(parts[1], message.TextPart)
    assert "/tmp/shot.png" in parts[1].text
    assert "LookAt" in parts[1].text
    # Original message must not be mutated
    assert isinstance(original.parts[1], message.ImageFilePart)


def test_developer_message_image_becomes_text_placeholder() -> None:
    original = message.DeveloperMessage(parts=[_image_file_part()])

    stripped = strip_images_for_text_only_model([original])

    part = stripped[0].parts[0]
    assert isinstance(part, message.TextPart)
    assert "/tmp/shot.png" in part.text


def test_tool_result_image_appends_placeholder_to_output_text() -> None:
    original = message.ToolResultMessage(
        status="success",
        output_text="[image] shot.png (10.0KB)",
        parts=[_image_file_part()],
    )

    stripped = strip_images_for_text_only_model([original])

    result = stripped[0]
    assert isinstance(result, message.ToolResultMessage)
    assert result.parts == []
    assert result.output_text.startswith("[image] shot.png (10.0KB)\n")
    assert "/tmp/shot.png" in result.output_text
    assert "LookAt" in result.output_text
    # Original message must not be mutated
    assert len(original.parts) == 1


def test_image_url_part_placeholder_uses_url() -> None:
    original = message.UserMessage(parts=[message.ImageURLPart(url="https://example.com/a.png")])

    stripped = strip_images_for_text_only_model([original])

    part = stripped[0].parts[0]
    assert isinstance(part, message.TextPart)
    assert "https://example.com/a.png" in part.text


def test_messages_without_images_pass_through_unchanged() -> None:
    user = message.UserMessage(parts=[message.TextPart(text="hi")])
    assistant = message.AssistantMessage(parts=[message.TextPart(text="ok")])

    stripped = strip_images_for_text_only_model([user, assistant])

    assert stripped[0] is user
    assert stripped[1] is assistant


def test_apply_config_defaults_strips_images_for_non_vision_model() -> None:
    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[_image_file_part()])],
    )

    param = apply_config_defaults(param, _config(supports_vision=False))

    assert param.supports_vision is False
    part = param.input[0].parts[0]
    assert isinstance(part, message.TextPart)


def test_apply_config_defaults_keeps_images_for_vision_model() -> None:
    original = message.UserMessage(parts=[_image_file_part()])
    param = llm_param.LLMCallParameter(input=[original])

    param = apply_config_defaults(param, _config(supports_vision=True))

    assert param.supports_vision is True
    assert param.input[0] is original
