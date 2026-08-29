from datetime import datetime

from klaude_code.log import debug_json


def test_debug_json_serializes_datetime_values() -> None:
    payload = {
        "create_time": datetime(2026, 2, 23, 12, 34, 56),
    }

    result = debug_json(payload)

    assert '"create_time": "2026-02-23T12:34:56"' in result


def test_debug_json_truncates_anthropic_image_blocks() -> None:
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "a" * 5000,
                        },
                    }
                ],
            }
        ]
    }

    result = debug_json(payload)

    assert "a" * 5000 not in result
    assert "truncated,len=5000" in result
    assert '"media_type": "image/png"' in result


def test_debug_json_truncates_data_url_strings() -> None:
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + "b" * 5000},
                    }
                ],
            }
        ]
    }

    result = debug_json(payload)

    assert "b" * 5000 not in result
    assert "truncated" in result
    # Prefix keeps the mime type identifiable.
    assert "data:image/png;base64" in result


def test_debug_json_redacts_credential_keys_at_any_depth() -> None:
    payload = {
        "provider": {"api_key": "sk-secret-123", "base_url": "https://api.example.com"},
        "nested": [{"aws_secret_key": "AKIA-secret", "aws_region": "us-east-1"}],
        "empty_key": {"api_key": None},
    }

    result = debug_json(payload)

    assert "sk-secret-123" not in result
    assert "AKIA-secret" not in result
    assert '"api_key": "***"' in result
    assert '"aws_secret_key": "***"' in result
    assert '"base_url": "https://api.example.com"' in result
    assert '"aws_region": "us-east-1"' in result
    # Empty credential values stay as-is (no fake redaction marker).
    assert '"api_key": null' in result


def test_debug_json_keeps_short_data_urls_and_plain_text() -> None:
    payload = {
        "icon": "data:image/gif;base64,R0lGOD",
        "text": "hello world",
    }

    result = debug_json(payload)

    assert '"icon": "data:image/gif;base64,R0lGOD"' in result
    assert '"text": "hello world"' in result
