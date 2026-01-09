from __future__ import annotations

import html
import importlib.resources
from functools import lru_cache
from pathlib import Path

import httpx

from klaude_code.const import TOOL_OUTPUT_TRUNCATION_DIR
from klaude_code.llm.image import get_assistant_image_output_dir

_MERMAID_INK_PREFIX = "https://mermaid.ink/img/pako:"
_MERMAID_DEFAULT_PNG_WIDTH = 1600
_MERMAID_DEFAULT_PNG_SCALE = 2


def artifacts_dir() -> Path:
    return Path(TOOL_OUTPUT_TRUNCATION_DIR)


def _extract_pako_from_link(link: str) -> str | None:
    """Extract pako encoded string from mermaid.live link."""
    # link format: https://mermaid.live/view#pako:xxxx
    if "#pako:" not in link:
        return None
    return link.split("#pako:", 1)[1]


def download_mermaid_png(
    *,
    link: str,
    tool_call_id: str,
    session_id: str | None = None,
) -> Path | None:
    """Download PNG image from mermaid.ink and save locally."""
    pako = _extract_pako_from_link(link)
    if not pako:
        return None

    safe_id = tool_call_id.replace("/", "_")
    output_dir = get_assistant_image_output_dir(session_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"mermaid-{safe_id}.png"

    if image_path.exists():
        return image_path

    png_url = (
        f"{_MERMAID_INK_PREFIX}{pako}?type=png&width={_MERMAID_DEFAULT_PNG_WIDTH}&scale={_MERMAID_DEFAULT_PNG_SCALE}"
    )
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(png_url)
            resp.raise_for_status()
            image_path.write_bytes(resp.content)
        return image_path
    except Exception:
        return None


@lru_cache(maxsize=1)
def load_template() -> str:
    template_file = importlib.resources.files("klaude_code.session.templates").joinpath("mermaid_viewer.html")
    return template_file.read_text(encoding="utf-8")


def ensure_viewer_file(*, code: str, link: str, tool_call_id: str) -> Path | None:
    """Create a local HTML viewer with large preview + editor."""

    if not tool_call_id:
        return None

    safe_id = tool_call_id.replace("/", "_")
    path = artifacts_dir() / f"klaude-mermaid-{safe_id}.html"
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


def build_viewer(*, code: str, link: str, tool_call_id: str) -> Path | None:
    """Create a local Mermaid viewer HTML file."""

    if not code:
        return None
    return ensure_viewer_file(code=code, link=link, tool_call_id=tool_call_id)
