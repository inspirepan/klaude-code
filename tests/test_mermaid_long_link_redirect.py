from __future__ import annotations

import html
from pathlib import Path

import pytest

from klaude_code import const
from klaude_code.tui.components import mermaid_viewer


def test_mermaid_long_link_creates_redirect_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(const, "TOOL_OUTPUT_TRUNCATION_DIR", str(tmp_path))

    link = "https://mermaid.live/view#pako:" + ("A" * 2100)
    code = "graph TD\n    A-->B\n    B-->C"
    path = mermaid_viewer.ensure_viewer_file(code=code, link=link, tool_call_id="call_test")

    assert path is not None
    assert path.exists()
    assert path.suffix == ".html"

    content = path.read_text(encoding="utf-8")
    assert "mermaid.live" in content
    assert link in content
    assert html.escape(code) in content
