"""Tests for UserInputPayload propagation through executor/agent/task chain."""

from klaude_code.protocol import message


def test_user_input_payload_creation_text_only() -> None:
    """Test creating UserInputPayload with text only."""
    payload = message.UserInputPayload(text="Hello, world!")
    assert payload.text == "Hello, world!"
    assert payload.images is None


def test_user_input_payload_creation_with_images() -> None:
    """Test creating UserInputPayload with text and images."""
    image = message.ImageURLPart(url="data:image/png;base64,abc123", id=None)
    payload = message.UserInputPayload(text="Check this image", images=[image])
    assert payload.text == "Check this image"
    assert payload.images is not None
    assert len(payload.images) == 1
    img = payload.images[0]
    assert isinstance(img, message.ImageURLPart)
    assert img.url == "data:image/png;base64,abc123"


def test_user_input_payload_images_preserved_in_user_message_item() -> None:
    """Test that images from UserInputPayload flow to UserMessage correctly."""
    image = message.ImageURLPart(url="data:image/png;base64,xyz789", id="img-1")
    payload = message.UserInputPayload(text="Image attached", images=[image])

    # Simulate what TaskExecutor.run does
    user_message = message.UserMessage(parts=message.parts_from_text_and_images(payload.text, payload.images))

    assert message.join_text_parts(user_message.parts) == "Image attached"
    image_parts = [part for part in user_message.parts if isinstance(part, message.ImageURLPart)]
    assert len(image_parts) == 1
    assert image_parts[0].id == "img-1"


def test_user_input_payload_multiple_images() -> None:
    """Test UserInputPayload with multiple images."""
    images: list[message.ImageURLPart | message.ImageFilePart] = [
        message.ImageURLPart(url=f"data:image/png;base64,img{i}", id=f"id-{i}") for i in range(3)
    ]
    payload = message.UserInputPayload(text="Multiple images", images=images)

    assert payload.images is not None
    assert len(payload.images) == 3
    for i, img in enumerate(payload.images):
        assert isinstance(img, message.ImageURLPart)
        assert img.id == f"id-{i}"


def test_user_input_payload_empty_text() -> None:
    """Test UserInputPayload with empty text but images."""
    image = message.ImageURLPart(url="data:image/png;base64,abc", id=None)
    payload = message.UserInputPayload(text="", images=[image])

    assert payload.text == ""
    assert payload.images is not None
    assert len(payload.images) == 1
