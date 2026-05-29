"""Characterization tests for reasoning handlers used by chat-completions streaming.

Covers DefaultReasoningHandler (openai_compatible) and the OpenRouter-specific
ReasoningStreamHandler, including the bare/broad ``except`` paths that silently
swallow malformed reasoning_details items. Locks in current behavior.
"""

from __future__ import annotations

from types import SimpleNamespace

from klaude_code.llm.openai_compatible.stream import DefaultReasoningHandler, ReasoningDeltaResult
from klaude_code.llm.openrouter.reasoning import ReasoningStreamHandler
from klaude_code.protocol import message

# --------------------------------------------------------------------------
# DefaultReasoningHandler
# --------------------------------------------------------------------------


def test_default_handler_plain_text_reasoning_content() -> None:
    handler = DefaultReasoningHandler(param_model="m", response_id="r")
    result = handler.on_delta(SimpleNamespace(reasoning_content="thinking"))
    assert result.handled is True
    assert result.outputs == ["thinking"]
    assert result.reasoning_field == "reasoning_content"


def test_default_handler_picks_first_field_and_sticks() -> None:
    # The first reasoning field seen is locked in for subsequent deltas.
    handler = DefaultReasoningHandler(param_model="m", response_id="r")
    handler.on_delta(SimpleNamespace(reasoning="r1"))
    result = handler.on_delta(SimpleNamespace(reasoning="r2"))
    assert result.reasoning_field == "reasoning"


def test_default_handler_no_reasoning_returns_unhandled() -> None:
    handler = DefaultReasoningHandler(param_model="m", response_id="r")
    result = handler.on_delta(SimpleNamespace(content="hi"))
    assert result == ReasoningDeltaResult(handled=False, outputs=[])


def test_default_handler_reasoning_details_take_priority() -> None:
    handler = DefaultReasoningHandler(param_model="m", response_id="r")
    delta = SimpleNamespace(
        reasoning_content="plain",
        reasoning_details=[{"type": "reasoning.text", "text": "structured", "format": "fmt-v1", "id": "rid"}],
    )
    result = handler.on_delta(delta)
    assert result.handled is True
    assert result.outputs == ["structured"]
    assert result.reasoning_field == "reasoning_details"
    assert result.reasoning_format == "fmt-v1"
    assert result.reasoning_id == "rid"


def test_default_handler_reasoning_details_encrypted_produces_signature_part() -> None:
    handler = DefaultReasoningHandler(param_model="m", response_id="r")
    delta = SimpleNamespace(
        reasoning_details=[{"type": "reasoning.encrypted", "data": "enc", "format": "f", "id": "x"}],
    )
    result = handler.on_delta(delta)
    assert len(result.outputs) == 1
    part = result.outputs[0]
    assert isinstance(part, message.ThinkingSignaturePart)
    assert part.signature == "enc"
    assert part.format == "f"
    assert part.id == "x"
    assert part.model_id == "m"


def test_default_handler_swallows_malformed_detail_items() -> None:
    # bare `except Exception: pass` => malformed items are silently dropped,
    # while valid ones in the same array are still processed.
    handler = DefaultReasoningHandler(param_model="m", response_id="r")
    delta = SimpleNamespace(
        reasoning_details=[
            {"type": 12345},  # type must be str -> ValidationError -> dropped
            {"type": "reasoning.text", "text": "ok"},
        ],
    )
    result = handler.on_delta(delta)
    assert result.handled is True
    assert result.outputs == ["ok"]


def test_default_handler_once_details_seen_plain_text_ignored() -> None:
    handler = DefaultReasoningHandler(param_model="m", response_id="r")
    handler.on_delta(SimpleNamespace(reasoning_details=[{"type": "reasoning.text", "text": "a"}]))
    # Subsequent plain-text reasoning is ignored to avoid duplication.
    result = handler.on_delta(SimpleNamespace(reasoning_content="plain"))
    assert result.handled is False
    assert result.outputs == []


# --------------------------------------------------------------------------
# OpenRouter ReasoningStreamHandler
# --------------------------------------------------------------------------


def test_openrouter_handler_no_details_unhandled() -> None:
    handler = ReasoningStreamHandler(param_model="m", response_id="r")
    result = handler.on_delta(SimpleNamespace(content="hi"))
    assert result.handled is False
    assert result.outputs == []


def test_openrouter_handler_text_with_signature() -> None:
    handler = ReasoningStreamHandler(param_model="m", response_id="r")
    delta = SimpleNamespace(
        reasoning_details=[
            {"type": "reasoning.text", "text": "thinking", "signature": "sig-1", "format": "anthropic", "id": "rid"}
        ]
    )
    result = handler.on_delta(delta)
    assert result.handled is True
    # text emitted first, then the signature part.
    assert result.outputs[0] == "thinking"
    sig = result.outputs[1]
    assert isinstance(sig, message.ThinkingSignaturePart)
    assert sig.signature == "sig-1"
    assert sig.format == "anthropic"
    assert sig.id == "rid"
    assert result.reasoning_format == "anthropic"


def test_openrouter_handler_encrypted_produces_signature_from_data() -> None:
    handler = ReasoningStreamHandler(param_model="m", response_id="r")
    delta = SimpleNamespace(
        reasoning_details=[{"type": "reasoning.encrypted", "data": "enc-data", "format": "openai", "id": "e1"}]
    )
    result = handler.on_delta(delta)
    assert result.handled is True
    parts = [o for o in result.outputs if isinstance(o, message.ThinkingSignaturePart)]
    assert len(parts) == 1
    assert parts[0].signature == "enc-data"
    assert parts[0].format == "openai"


def test_openrouter_handler_swallows_malformed_items() -> None:
    # broad `except Exception` (logs and continues) => malformed item dropped,
    # subsequent valid item still handled. Result is still handled=True.
    handler = ReasoningStreamHandler(param_model="m", response_id="r")
    delta = SimpleNamespace(
        reasoning_details=[
            {"type": 999},  # invalid type -> ValidationError -> logged + dropped
            {"type": "reasoning.text", "text": "kept"},
        ]
    )
    result = handler.on_delta(delta)
    assert result.handled is True
    assert "kept" in result.outputs


def test_openrouter_handler_flush_returns_empty() -> None:
    handler = ReasoningStreamHandler(param_model="m", response_id="r")
    assert handler.flush() == []
