# pyright: reportPrivateUsage=false
"""Property-based tests for session codec module."""

from datetime import datetime
from typing import TYPE_CHECKING

from hypothesis import given, settings
from hypothesis import strategies as st

if TYPE_CHECKING:
    from klaude_code.protocol import model


# ============================================================================
# Strategy generators for conversation items
# ============================================================================


@st.composite
def user_message_items(draw: st.DrawFn) -> "model.UserMessageItem":
    """Generate UserMessageItem instances."""
    from klaude_code.protocol.model import UserMessageItem

    return UserMessageItem(
        id=draw(st.none() | st.text(min_size=1, max_size=20)),
        content=draw(st.none() | st.text(min_size=0, max_size=100)),
        created_at=datetime.now(),
    )


@st.composite
def assistant_message_items(draw: st.DrawFn) -> "model.AssistantMessageItem":
    """Generate AssistantMessageItem instances."""
    from klaude_code.protocol.model import AssistantMessageItem

    return AssistantMessageItem(
        id=draw(st.none() | st.text(min_size=1, max_size=20)),
        content=draw(st.none() | st.text(min_size=0, max_size=100)),
        response_id=draw(st.none() | st.text(min_size=1, max_size=20)),
        created_at=datetime.now(),
    )


@st.composite
def tool_call_items(draw: st.DrawFn) -> "model.ToolCallItem":
    """Generate ToolCallItem instances."""
    from klaude_code.protocol.model import ToolCallItem

    return ToolCallItem(
        id=draw(st.none() | st.text(min_size=1, max_size=20)),
        call_id=draw(st.text(min_size=1, max_size=20)),
        name=draw(st.text(min_size=1, max_size=20)),
        arguments=draw(st.text(min_size=0, max_size=100)),
        created_at=datetime.now(),
    )


@st.composite
def start_items(draw: st.DrawFn) -> "model.StartItem":
    """Generate StartItem instances."""
    from klaude_code.protocol.model import StartItem

    return StartItem(
        response_id=draw(st.text(min_size=1, max_size=20)),
        created_at=datetime.now(),
    )


def interrupt_items() -> st.SearchStrategy["model.InterruptItem"]:
    """Generate InterruptItem instances."""
    from klaude_code.protocol.model import InterruptItem

    return st.builds(InterruptItem, created_at=st.just(datetime.now()))


conversation_items = st.one_of(
    user_message_items(),
    assistant_message_items(),
    tool_call_items(),
    start_items(),
    interrupt_items(),
)


# ============================================================================
# Property-based tests
# ============================================================================


@given(item=conversation_items)
@settings(max_examples=100, deadline=None)
def test_codec_encode_decode_roundtrip(item: "model.ConversationItem") -> None:
    """Property: decode(encode(item)) == item (for content fields)."""
    from klaude_code.session.codec import decode_conversation_item, encode_conversation_item

    encoded = encode_conversation_item(item)
    decoded = decode_conversation_item(encoded)

    assert decoded is not None
    assert type(decoded) is type(item)
    # Compare key fields (created_at may differ due to datetime serialization)
    assert decoded.model_dump(exclude={"created_at"}) == item.model_dump(exclude={"created_at"})


@given(item=conversation_items)
@settings(max_examples=100, deadline=None)
def test_codec_jsonl_roundtrip(item: "model.ConversationItem") -> None:
    """Property: jsonl decode(encode(item)) == item."""
    from klaude_code.session.codec import decode_jsonl_line, encode_jsonl_line

    encoded = encode_jsonl_line(item)
    decoded = decode_jsonl_line(encoded)

    assert decoded is not None
    assert type(decoded) is type(item)
    assert decoded.model_dump(exclude={"created_at"}) == item.model_dump(exclude={"created_at"})
