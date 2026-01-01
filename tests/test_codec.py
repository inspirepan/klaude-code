# pyright: reportPrivateUsage=false
"""Property-based tests for session codec module."""

from datetime import datetime
from typing import TYPE_CHECKING

from hypothesis import given, settings
from hypothesis import strategies as st

if TYPE_CHECKING:
    from klaude_code.protocol import model


# ============================================================================
# Strategy generators for history items
# ============================================================================


@st.composite
def user_message_items(draw: st.DrawFn) -> "model.UserMessage":
    """Generate UserMessage instances."""
    from klaude_code.protocol.model import UserMessage, text_parts_from_str

    text = draw(st.none() | st.text(min_size=0, max_size=100))
    return UserMessage(
        id=draw(st.none() | st.text(min_size=1, max_size=20)),
        parts=text_parts_from_str(text),
        created_at=datetime.now(),
    )


@st.composite
def assistant_message_items(draw: st.DrawFn) -> "model.AssistantMessage":
    """Generate AssistantMessage instances."""
    from klaude_code.protocol.model import AssistantMessage, text_parts_from_str

    text = draw(st.none() | st.text(min_size=0, max_size=100))
    return AssistantMessage(
        id=draw(st.none() | st.text(min_size=1, max_size=20)),
        parts=text_parts_from_str(text),
        response_id=draw(st.none() | st.text(min_size=1, max_size=20)),
        created_at=datetime.now(),
    )


@st.composite
def tool_result_messages(draw: st.DrawFn) -> "model.ToolResultMessage":
    """Generate ToolResultMessage instances."""
    from klaude_code.protocol.model import ToolResultMessage

    return ToolResultMessage(
        call_id=draw(st.text(min_size=1, max_size=20)),
        tool_name=draw(st.text(min_size=1, max_size=20)),
        status=draw(st.sampled_from(["success", "error", "aborted"])),
        output_text=draw(st.text(min_size=0, max_size=100)),
        created_at=datetime.now(),
    )


def stream_error_items() -> st.SearchStrategy["model.StreamErrorItem"]:
    """Generate StreamErrorItem instances."""
    from klaude_code.protocol.model import StreamErrorItem

    return st.builds(StreamErrorItem, error=st.text(min_size=1, max_size=100), created_at=st.just(datetime.now()))


def task_metadata_items() -> st.SearchStrategy["model.TaskMetadataItem"]:
    """Generate TaskMetadataItem instances."""
    from klaude_code.protocol.model import TaskMetadataItem

    return st.builds(TaskMetadataItem, created_at=st.just(datetime.now()))


history_items = st.one_of(
    user_message_items(),
    assistant_message_items(),
    tool_result_messages(),
    stream_error_items(),
    task_metadata_items(),
)


# ============================================================================
# Property-based tests
# ============================================================================


@given(item=history_items)
@settings(max_examples=100, deadline=None)
def test_codec_encode_decode_roundtrip(item: "model.HistoryEvent") -> None:
    """Property: decode(encode(item)) == item (for content fields)."""
    from klaude_code.session.codec import decode_conversation_item, encode_conversation_item

    encoded = encode_conversation_item(item)
    decoded = decode_conversation_item(encoded)

    assert decoded is not None
    assert type(decoded) is type(item)
    # Compare key fields (created_at may differ due to datetime serialization)
    assert decoded.model_dump(exclude={"created_at"}) == item.model_dump(exclude={"created_at"})


@given(item=history_items)
@settings(max_examples=100, deadline=None)
def test_codec_jsonl_roundtrip(item: "model.HistoryEvent") -> None:
    """Property: jsonl decode(encode(item)) == item."""
    from klaude_code.session.codec import decode_jsonl_line, encode_jsonl_line

    encoded = encode_jsonl_line(item)
    decoded = decode_jsonl_line(encoded)

    assert decoded is not None
    assert type(decoded) is type(item)
    assert decoded.model_dump(exclude={"created_at"}) == item.model_dump(exclude={"created_at"})
