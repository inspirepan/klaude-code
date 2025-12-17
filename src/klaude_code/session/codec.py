from __future__ import annotations

import json
from typing import Any, TypeGuard, cast, get_args

from pydantic import BaseModel

from klaude_code.protocol import model


def _is_basemodel_subclass(tp: object) -> TypeGuard[type[BaseModel]]:
    return isinstance(tp, type) and issubclass(tp, BaseModel)


def _flatten_union(tp: object) -> list[object]:
    args = list(get_args(tp))
    if not args:
        return [tp]
    flattened: list[object] = []
    for arg in args:
        flattened.extend(_flatten_union(arg))
    return flattened


def _build_type_registry() -> dict[str, type[BaseModel]]:
    registry: dict[str, type[BaseModel]] = {}
    for tp in _flatten_union(model.ConversationItem):
        if not _is_basemodel_subclass(tp):
            continue
        registry[tp.__name__] = tp
    return registry


_CONVERSATION_ITEM_TYPES: dict[str, type[BaseModel]] = _build_type_registry()


def encode_conversation_item(item: model.ConversationItem) -> dict[str, Any]:
    return {"type": item.__class__.__name__, "data": item.model_dump(mode="json")}


def decode_conversation_item(obj: dict[str, Any]) -> model.ConversationItem | None:
    t = obj.get("type")
    data = obj.get("data", {})
    if not isinstance(t, str) or not isinstance(data, dict):
        return None
    cls = _CONVERSATION_ITEM_TYPES.get(t)
    if cls is None:
        return None
    try:
        item = cls(**data)
    except TypeError:
        return None
    # pyright: ignore[reportReturnType]
    return item  # type: ignore[return-value]


def encode_jsonl_line(item: model.ConversationItem) -> str:
    return json.dumps(encode_conversation_item(item), ensure_ascii=False) + "\n"


def decode_jsonl_line(line: str) -> model.ConversationItem | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return decode_conversation_item(cast(dict[str, Any], obj))
