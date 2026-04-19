from datetime import datetime

from klaude_code.log import debug_json


def test_debug_json_serializes_datetime_values() -> None:
    payload = {
        "create_time": datetime(2026, 2, 23, 12, 34, 56),
    }

    result = debug_json(payload)

    assert '"create_time": "2026-02-23T12:34:56"' in result
