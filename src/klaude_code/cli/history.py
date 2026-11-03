"""Local history picker with read-only previews and execution-lease guards."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from prompt_toolkit.application.current import get_app
from pydantic import BaseModel
from rich.cells import cell_len, set_cell_size
from rich.console import Console
from rich.text import Text

from klaude_code.app.session_index import SessionIndex, SessionSummary, SessionTargetError, resolve_session_target
from klaude_code.app.session_lease import SessionLease
from klaude_code.const import ProjectPaths, project_key_from_path
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, select_one

_PREVIEW_BYTES = 128 * 1024
_WRAP_CONSOLE = Console()


class _PreviewEntry(BaseModel):
    mtime_ns: int
    size: int
    text: str


def _plain(text: str) -> str:
    return " ".join("".join(char for char in text if char.isprintable() or char.isspace()).split())


def _fit(text: str, width: int) -> str:
    width = max(1, width)
    return text if cell_len(text) <= width else set_cell_size(text, width - 1).rstrip() + "…"


def _assistant_preview(path: Path, size: int) -> str:
    try:
        with path.open("rb") as file:
            offset = max(0, size - _PREVIEW_BYTES)
            file.seek(offset)
            tail = file.read(_PREVIEW_BYTES)
    except OSError:
        return ""
    lines = tail.splitlines()
    if offset and lines:
        lines = lines[1:]
    if tail and not tail.endswith(b"\n"):
        lines = lines[:-1]
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "RewindEntry":
            return ""
        if entry.get("type") != "AssistantMessage" or not isinstance(entry.get("data"), dict):
            continue
        parts = entry["data"].get("parts")
        if not isinstance(parts, list):
            continue
        text = " ".join(
            part["text"]
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        )
        if text := _plain(text):
            return text[:2048]
    return ""


def _preview(session: SessionSummary, cache: dict[Path, _PreviewEntry] | None = None) -> str:
    path = ProjectPaths(project_key=project_key_from_path(Path(session.work_dir))).events_file(session.id)
    try:
        stamp = path.stat()
        entry = cache.get(path) if cache is not None else None
        if entry is None or entry.mtime_ns != stamp.st_mtime_ns or entry.size != stamp.st_size:
            entry = _PreviewEntry(
                mtime_ns=stamp.st_mtime_ns, size=stamp.st_size, text=_assistant_preview(path, stamp.st_size)
            )
            if cache is not None:
                cache[path] = entry
        text = entry.text
    except OSError:
        text = ""
    return text or next((_plain(text) for text in reversed(session.user_messages) if _plain(text)), "No messages yet")


def _date_group(updated: datetime, today: datetime) -> str:
    if updated.date() == today.date():
        return "Today"
    if updated.date() == today.date() - timedelta(days=1):
        return "Yesterday"
    return updated.strftime("%Y-%m-%d")


def build_history_items(
    sessions: list[SessionSummary],
    *,
    active_ids: set[str],
    columns: int,
    now: datetime | None = None,
    preview_cache: dict[Path, _PreviewEntry] | None = None,
) -> list[SelectItem[str]]:
    now = now or datetime.now()
    width = max(1, columns - 4)
    items: list[SelectItem[str]] = []
    group = None
    for session in sessions:
        updated = datetime.fromtimestamp(session.updated_at)
        next_group = _date_group(updated, now)
        if next_group != group:
            items.append(
                SelectItem(
                    title=[("class:meta", _fit(next_group, width) + "\n")], value=None, search_text="", selectable=False
                )
            )
            group = next_group
        active = session.id in active_ids
        title = _plain(session.title or session.name or next(iter(session.user_messages), "Untitled session"))
        directory = _plain(Path(session.work_dir).name or session.work_dir)
        tail = "already open" if active else updated.strftime("%H:%M")
        if width >= 70 and not active:
            tail += " · " + session.id[:8]
        if width < 32 and active:
            tail = "open"
        tail = _fit(tail, max(1, width // 2))
        leading_width = max(1, width - cell_len(tail) - 2)
        directory = _fit(directory, min(24, max(1, leading_width // 3))) if leading_width >= 12 else ""
        title = _fit(title, max(1, leading_width - cell_len(directory) - (2 if directory else 0)))
        gap = max(1, width - cell_len(title) - cell_len(directory) - cell_len(tail) - (2 if directory else 0))
        tokens = [("class:meta" if active else "class:msg bold", title)]
        if directory:
            tokens.append(("class:meta", "  " + directory))
        tokens.append(("class:meta", " " * gap + tail + "\n"))
        if width < 8:
            tokens = [("class:meta" if active else "class:msg bold", _fit(title, width) + "\n")]
        preview = _preview(session, preview_cache)
        wrapped = Text(preview).wrap(_WRAP_CONSOLE, width, overflow="fold")
        for index, line in enumerate(wrapped[:2]):
            text = _fit(line.plain + ("…" if index == 1 and len(wrapped) > 2 else ""), width)
            tokens.append(("class:meta", set_cell_size(text, width) + "\n"))
        tokens.append(("", "\n"))
        items.append(
            SelectItem(
                title=tokens,
                value=session.id,
                search_text=" ".join(
                    [
                        session.title or "",
                        session.name or "",
                        session.id,
                        session.work_dir,
                        preview,
                        *session.user_messages,
                    ]
                ),
                selectable=not active,
            )
        )
    return items


def _reject_active(session: SessionSummary) -> None:
    if SessionLease.is_active(session.id):
        raise ValueError(f"Session {session.id} is already open in another Klaude process; return to its terminal")


def select_history(target: str | None = None) -> SessionSummary | None:
    index = SessionIndex(home=Path.home())
    index.reload()
    sessions = [item for item in index.list_all() if not item.archived and item.parent_session_id is None]
    if target is not None:
        try:
            selected = resolve_session_target(sessions, target)
        except SessionTargetError as exc:
            if exc.status_code == 404:
                raise ValueError(f"Session not found: {target}") from None
            raise
        _reject_active(selected)
        return selected
    sessions = sorted(
        (item for item in sessions if Path(item.work_dir).resolve() == Path.cwd().resolve()),
        key=lambda item: item.updated_at,
        reverse=True,
    )
    if not sessions:
        return None
    current_items: list[SelectItem[str]] = []
    preview_cache: dict[Path, _PreviewEntry] = {}

    def provide_items() -> list[SelectItem[str]]:
        nonlocal current_items
        columns = get_app().output.get_size().columns or shutil.get_terminal_size((80, 24)).columns
        current_items = build_history_items(
            sessions,
            columns=columns,
            active_ids={item.id for item in sessions if SessionLease.is_active(item.id)},
            preview_cache=preview_cache,
        )
        return current_items

    def style_item(tokens: list[tuple[str, str]], index: int, pointed: int) -> list[tuple[str, str]]:
        if index != pointed or not current_items[index].selectable:
            return tokens
        return [(style + " class:history.selected", text) if text.strip() else (style, text) for style, text in tokens]

    selected_id = select_one(
        message="Resume a session",
        items=provide_items(),
        items_provider=provide_items,
        style=DEFAULT_PICKER_STYLE(),
        use_search_filter=True,
        highlight_pointed_item=False,
        item_style_transform=style_item,
    )
    selected = next((item for item in sessions if item.id == selected_id), None)
    if selected is not None:
        _reject_active(selected)
    return selected
