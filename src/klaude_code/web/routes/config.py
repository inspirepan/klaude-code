from __future__ import annotations

from pathlib import Path
from typing import Final

from fastapi import APIRouter, Depends, Query

from klaude_code.config import load_config
from klaude_code.config.formatters import format_model_params
from klaude_code.web.state import WebAppState, get_web_state

router = APIRouter(prefix="/api/config", tags=["config"])
_WEB_STATE_DEP: Final = Depends(get_web_state)


@router.get("/models")
async def list_models() -> dict[str, list[dict[str, str | bool | list[str]]]]:
    config = load_config()
    entries = config.iter_model_entries(only_available=True, include_disabled=False)
    default_model = (config.main_model or "").strip()
    models = [
        {
            "name": entry.selector,
            "provider": entry.provider,
            "model_name": entry.model_name,
            "model_id": entry.model_id or entry.model_name,
            "params": format_model_params(entry),
            "is_default": entry.selector == default_model or entry.model_name == default_model,
        }
        for entry in entries
    ]
    return {"models": models}


def _get_input_history_path(work_dir: Path, home_dir: Path) -> Path:
    """Derive the input_history.txt path, matching prompt_toolkit.py logic."""
    project = str(work_dir).strip("/").replace("/", "-")
    return home_dir / ".klaude" / "projects" / project / "input" / "input_history.txt"


def _parse_input_history(text: str, limit: int) -> list[str]:
    """Parse prompt_toolkit FileHistory format into a list of entries (newest first).

    Format: entries separated by blank/comment lines, each content line starts with '+'.
    """
    entries: list[str] = []
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("+"):
            current_lines.append(line[1:])
        else:
            if current_lines:
                entries.append("\n".join(current_lines))
                current_lines = []

    if current_lines:
        entries.append("\n".join(current_lines))

    # FileHistory stores oldest first; reverse for newest first, then deduplicate.
    seen: set[str] = set()
    result: list[str] = []
    for entry in reversed(entries):
        stripped = entry.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            result.append(stripped)
            if len(result) >= limit:
                break

    return result


@router.get("/input-history")
async def get_input_history(
    state: WebAppState = _WEB_STATE_DEP,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, list[str]]:
    """Return recent input history entries (newest first, deduplicated)."""
    history_path = _get_input_history_path(state.work_dir, state.home_dir)
    if not history_path.is_file():
        return {"entries": []}
    text = history_path.read_text(encoding="utf-8", errors="replace")
    return {"entries": _parse_input_history(text, limit)}
