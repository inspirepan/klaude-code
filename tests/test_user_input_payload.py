"""Tests for UserInputPayload propagation through executor/agent/task chain."""

from klaude_code.protocol import model


def test_user_input_payload_creation_text_only() -> None:
    """Test creating UserInputPayload with text only."""
    payload = model.UserInputPayload(text="Hello, world!")
    assert payload.text == "Hello, world!"
    assert payload.images is None


def test_user_input_payload_creation_with_images() -> None:
    """Test creating UserInputPayload with text and images."""
    image = model.ImageURLPart(url="data:image/png;base64,abc123", id=None)
    payload = model.UserInputPayload(text="Check this image", images=[image])
    assert payload.text == "Check this image"
    assert payload.images is not None
    assert len(payload.images) == 1
    assert payload.images[0].url == "data:image/png;base64,abc123"


def test_user_input_payload_images_preserved_in_user_message_item() -> None:
    """Test that images from UserInputPayload flow to UserMessage correctly."""
    image = model.ImageURLPart(url="data:image/png;base64,xyz789", id="img-1")
    payload = model.UserInputPayload(text="Image attached", images=[image])

    # Simulate what TaskExecutor.run does
    user_message = model.UserMessage(parts=model.parts_from_text_and_images(payload.text, payload.images))

    assert model.join_text_parts(user_message.parts) == "Image attached"
    image_parts = [part for part in user_message.parts if isinstance(part, model.ImageURLPart)]
    assert len(image_parts) == 1
    assert image_parts[0].id == "img-1"


def test_user_input_payload_multiple_images() -> None:
    """Test UserInputPayload with multiple images."""
    images = [model.ImageURLPart(url=f"data:image/png;base64,img{i}", id=f"id-{i}") for i in range(3)]
    payload = model.UserInputPayload(text="Multiple images", images=images)

    assert payload.images is not None
    assert len(payload.images) == 3
    for i, img in enumerate(payload.images):
        assert img.id == f"id-{i}"


def test_user_input_payload_empty_text() -> None:
    """Test UserInputPayload with empty text but images."""
    image = model.ImageURLPart(url="data:image/png;base64,abc", id=None)
    payload = model.UserInputPayload(text="", images=[image])

    assert payload.text == ""
    assert payload.images is not None
    assert len(payload.images) == 1
