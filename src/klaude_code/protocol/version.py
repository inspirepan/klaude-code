from __future__ import annotations

PROTOCOL_VERSION = 1


def is_protocol_compatible(value: object) -> bool:
    """Return whether a peer speaks the exact supported wire protocol."""

    return type(value) is int and value == PROTOCOL_VERSION
