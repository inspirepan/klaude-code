from __future__ import annotations

import asyncio
import base64
import json
import zlib

import pytest

from klaude_code.core.tool import MermaidTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.protocol.model import MermaidLinkUIExtra


def _tool_context() -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test")


def _decode_payload(link: str) -> dict[str, object]:
    prefix = "https://mermaid.live/view#pako:"
    if not link.startswith(prefix):
        msg = "Unexpected Mermaid live URL prefix"
        raise AssertionError(msg)
    payload = link[len(prefix) :]
    padding = "=" * (-len(payload) % 4)
    compressed = base64.urlsafe_b64decode(payload + padding)
    decoded = zlib.decompress(compressed).decode("utf-8")
    return json.loads(decoded)


def test_mermaid_tool_generates_shareable_link(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = "graph TD\n    A-->B\n    B-->C"
    args = MermaidTool.MermaidArguments(code=code).model_dump_json()

    result = asyncio.run(MermaidTool.call(args, _tool_context()))

    assert result.status == "success"
    assert isinstance(result.ui_extra, MermaidLinkUIExtra)

    link = result.ui_extra.link
    print(f"Mermaid link: {link}")

    payload = _decode_payload(link)
    assert payload["code"] == code
    assert result.ui_extra.line_count == 3
