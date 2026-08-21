"""Tests for the client env-sync wire framing."""

from __future__ import annotations

import base64

from klaude_code.protocol.env_sync import (
    ENV_SYNC_HEADER,
    ENV_SYNC_HEADER_ASGI,
    decode_env_header,
    encode_env_header,
)


def test_encode_decode_round_trip() -> None:
    values = {"OPENROUTER_API_KEY": "sk-abc", "YOUTU_API_KEY": "sk-def"}

    header = encode_env_header(values)

    assert header.isascii()
    assert "sk-abc" not in header  # opaque on the wire
    assert decode_env_header(header) == values


def test_decode_handles_asgi_bytes_form() -> None:
    header = encode_env_header({"A": "b"})

    assert decode_env_header(header.encode("ascii")) == {"A": "b"}


def test_decode_ignores_malformed_or_non_object_input() -> None:
    assert decode_env_header("!!!not-base64-json!!!") is None
    non_object = base64.b64encode(b'["not-an-object"]')
    assert decode_env_header(non_object) is None


def test_decode_filters_invalid_env_names() -> None:
    header = encode_env_header({"GOOD_KEY": "v", "1BAD": "v", "bad-name": "v"})

    assert decode_env_header(header) == {"GOOD_KEY": "v"}


def test_header_constants_agree() -> None:
    assert ENV_SYNC_HEADER.encode("ascii").lower() == ENV_SYNC_HEADER_ASGI
