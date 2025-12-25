from __future__ import annotations

import base64
import html
import importlib.resources
import json
import zlib
from functools import lru_cache
from pathlib import Path

from klaude_code import const


def artifacts_dir() -> Path:
    return Path(const.TOOL_OUTPUT_TRUNCATION_DIR) / "mermaid"


def decode_mermaid_live_link(link: str) -> str | None:
    """Decode Mermaid.live pako link and return Mermaid code."""

    if "#pako:" not in link:
        return None

    payload = link.split("#pako:", 1)[1]
    if not payload:
        return None

    try:
        padding = "=" * (-len(payload) % 4)
        compressed = base64.urlsafe_b64decode(payload + padding)
        decoded = zlib.decompress(compressed).decode("utf-8")
        state = json.loads(decoded)
    except (ValueError, zlib.error, json.JSONDecodeError):
        return None

    if not isinstance(state, dict):
        return None
    code = state.get("code")  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    return code if isinstance(code, str) else None


@lru_cache(maxsize=1)
def load_template() -> str:
    template_file = importlib.resources.files("klaude_code.session.templates").joinpath("mermaid_viewer.html")
    return template_file.read_text(encoding="utf-8")


def ensure_viewer_file(*, code: str, link: str, tool_call_id: str) -> Path | None:
    """Create a local HTML viewer with large preview + editor."""

    if not tool_call_id:
        return None

    safe_id = tool_call_id.replace("/", "_")
    path = artifacts_dir() / f"mermaid-viewer-{safe_id}.html"
    if path.exists():
        return path

    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        escaped_code = html.escape(code)
        escaped_view_link = html.escape(link, quote=True)
        escaped_edit_link = html.escape(link.replace("/view#pako:", "/edit#pako:"), quote=True)

        template = load_template()
        content = (
            template.replace("__KLAUDE_VIEW_LINK__", escaped_view_link)
            .replace("__KLAUDE_EDIT_LINK__", escaped_edit_link)
            .replace("__KLAUDE_CODE__", escaped_code)
        )
        path.write_text(content, encoding="utf-8")
    except OSError:
        return None

    return path


def build_viewer_from_link(*, link: str, tool_call_id: str) -> Path | None:
    code = decode_mermaid_live_link(link)
    if not code:
        return None
    return ensure_viewer_file(code=code, link=link, tool_call_id=tool_call_id)
