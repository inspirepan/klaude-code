from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def canonicalize_json(value: object) -> JsonValue:
    """Return a JSON-equivalent value with stable dict key ordering.

    This is used to make provider payload serialization stable across runs so that
    prefix caching has a better chance to hit.
    """

    if isinstance(value, Mapping):
        items: list[tuple[str, JsonValue]] = []
        for key, item_value in cast(Mapping[object, object], value).items():
            items.append((str(key), canonicalize_json(item_value)))
        items.sort(key=lambda kv: kv[0])
        return {k: v for k, v in items}

    if isinstance(value, list):
        return [canonicalize_json(v) for v in cast(list[object], value)]

    if isinstance(value, tuple):
        return [canonicalize_json(v) for v in cast(tuple[object, ...], value)]

    return cast(JsonValue, value)


def dumps_canonical_json(value: object) -> str:
    """Dump JSON with stable key order and no insignificant whitespace."""

    canonical = canonicalize_json(value)
    return json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
