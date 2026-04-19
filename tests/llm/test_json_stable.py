from __future__ import annotations

from klaude_code.llm.json_stable import canonicalize_json, dumps_canonical_json


def test_dumps_canonical_json_sorts_keys() -> None:
    value = {"b": 1, "a": 2}
    assert dumps_canonical_json(value) == '{"a":2,"b":1}'


def test_dumps_canonical_json_sorts_nested_dict_keys() -> None:
    value = {
        "b": {"d": 4, "c": 3},
        "a": [{"y": 2, "x": 1}, 2],
    }
    assert dumps_canonical_json(value) == '{"a":[{"x":1,"y":2},2],"b":{"c":3,"d":4}}'


def test_canonicalize_json_preserves_list_order() -> None:
    value = {"a": [3, 2, 1], "b": ["z", "y", "x"]}
    assert canonicalize_json(value) == {"a": [3, 2, 1], "b": ["z", "y", "x"]}
