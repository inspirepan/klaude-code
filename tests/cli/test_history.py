from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from rich.cells import cell_len

from klaude_code.app.session_index import SessionSummary, load_session_summary_from_meta
from klaude_code.app.session_lease import SessionLease
from klaude_code.cli import history
from klaude_code.protocol import message
from klaude_code.session import Session
from klaude_code.session.codec import encode_jsonl_line
from klaude_code.session.store_registry import close_default_store, get_store_for_path


def saved(
    work_dir: Path, *, title: str = "历史标题", reply: str = "最近回复内容", updated: datetime | None = None
) -> SessionSummary:
    session = Session.create(work_dir=work_dir)
    session.title = title
    session.ensure_meta_exists()

    async def append() -> None:
        session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("最近用户输入")),
                message.AssistantMessage(
                    parts=[message.ThinkingTextPart(text="private reasoning"), message.TextPart(text=reply)]
                ),
            ]
        )
        await session.wait_for_flush()
        await close_default_store()

    asyncio.run(append())
    store = get_store_for_path(work_dir)
    if updated is not None:
        store.update_meta(session.id, {"updated_at": updated.timestamp()})
    summary = load_session_summary_from_meta(store.load_meta(session.id) or {}, fallback_session_id=session.id)
    assert summary is not None
    return summary


@pytest.mark.parametrize("columns", [10, 24, 40, 60, 80, 120])
def test_history_cards_group_preview_and_fit_cjk_cells(tmp_path: Path, columns: int) -> None:
    now = datetime(2026, 11, 3, 12)
    recent = saved(
        tmp_path,
        title="开始实现本地 TUI Runtime " * 5,
        reply="最近的助手回复 mixed words and 中文内容。" * 15,
        updated=now,
    )
    old = saved(tmp_path, updated=now - timedelta(days=1))
    items = history.build_history_items([recent, old], active_ids={recent.id}, columns=columns, now=now)
    assert [item.value for item in items if not item.is_header] == [recent.id, old.id]
    assert [item.selectable for item in items if not item.is_header] == [False, True]
    assert any("Today" in text or "Today".startswith(text.strip("…\n")) for _, text in items[0].title)
    if columns >= 24:
        assert "Yesterday" in "".join(text for _, text in items[2].title)
        assert "open" in "".join(text for _, text in items[1].title)
    for item in items:
        for line in "".join(text for _, text in item.title).splitlines():
            assert cell_len(line) <= columns - 4
    assert "最近的助手回复" in items[1].search_text
    assert "private reasoning" not in str(items)


def test_preview_uses_bounded_tail_skips_partial_and_tool_only_messages(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    complete = encode_jsonl_line(
        message.AssistantMessage(parts=message.text_parts_from_str("last complete reply"))
    ).encode()
    tool_only = encode_jsonl_line(
        message.AssistantMessage(parts=[message.ToolCallPart(call_id="x", tool_name="Read", arguments_json="{}")])
    ).encode()
    path.write_bytes(
        b"x" * (history._PREVIEW_BYTES + 50) + b"\n" + complete + tool_only + b'{"type":"AssistantMessage", "data":'
    )
    stamp = path.stat()
    assert history._assistant_preview(path, stamp.st_size) == "last complete reply"
    path.write_bytes(
        complete
        + encode_jsonl_line(message.AssistantMessage(parts=message.text_parts_from_str("fresh reply"))).encode()
    )
    stamp = path.stat()
    assert history._assistant_preview(path, stamp.st_size) == "fresh reply"


def test_history_picker_shows_active_and_enables_after_owner_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    active, idle = saved(tmp_path, title="open session"), saved(tmp_path, title="saved session")
    other = saved(tmp_path / "other", title="other directory")
    lease = SessionLease(active.id)
    metadata = get_store_for_path(tmp_path).paths.meta_file(active.id)
    before = metadata.read_bytes()
    try:

        def choose(**kwargs: Any) -> str:
            provider = kwargs["items_provider"]
            rows = {item.value: item for item in provider() if not item.is_header}
            assert rows[active.id].selectable is False
            assert rows[idle.id].selectable is True
            assert other.id not in rows
            lease.close()
            rows = {item.value: item for item in provider() if not item.is_header}
            assert rows[active.id].selectable is True
            return active.id

        monkeypatch.setattr(history, "select_one", choose)
        result = history.select_history()
        assert result is not None and result.id == active.id
        assert metadata.read_bytes() == before
    finally:
        lease.close()


def test_explicit_target_refuses_open_idle_session_and_allows_after_close(tmp_path: Path) -> None:
    summary = saved(tmp_path)
    lease = SessionLease(summary.id)
    try:
        assert SessionLease.is_active(summary.id)
        with pytest.raises(ValueError, match="already open"):
            history.select_history(summary.id)
    finally:
        lease.close()
    result = history.select_history(summary.id[:12])
    assert result is not None and result.id == summary.id


def test_selection_is_rechecked_before_returning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    summary = saved(tmp_path)
    leases: list[SessionLease] = []

    def choose(**_kwargs: Any) -> str:
        leases.append(SessionLease(summary.id))
        return summary.id

    monkeypatch.setattr(history, "select_one", choose)
    try:
        with pytest.raises(ValueError, match="already open"):
            history.select_history()
    finally:
        for lease in leases:
            lease.close()


def test_probe_does_not_create_a_lease_or_runtime(isolated_home: Path) -> None:
    assert not SessionLease.is_active("missing")
    assert not (isolated_home / ".klaude" / "run").exists()


def test_preview_falls_back_without_replaying_legacy_rewind(tmp_path: Path) -> None:
    summary = saved(tmp_path)
    path = get_store_for_path(tmp_path).paths.events_file(summary.id)
    with path.open("a") as file:
        file.write(json.dumps({"type": "RewindEntry", "data": {}}) + "\n")
    items = history.build_history_items([summary], active_ids=set(), columns=80)
    assert "最近用户输入" in items[1].search_text
    assert "最近回复内容" not in items[1].search_text


def test_picker_caches_one_preview_per_file_and_refreshes_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = saved(tmp_path, reply="first reply")
    original = history._assistant_preview
    reads: list[Path] = []

    def read(path: Path, size: int) -> str:
        reads.append(path)
        return original(path, size)

    monkeypatch.setattr(history, "_assistant_preview", read)
    cache: dict[Path, history._PreviewEntry] = {}
    assert history._preview(summary, cache) == "first reply"
    assert history._preview(summary, cache) == "first reply"
    assert len(reads) == 1
    path = get_store_for_path(tmp_path).paths.events_file(summary.id)
    with path.open("a") as file:
        file.write(encode_jsonl_line(message.AssistantMessage(parts=message.text_parts_from_str("new reply"))))
    assert history._preview(summary, cache) == "new reply"
    assert len(reads) == 2 and len(cache) == 1
