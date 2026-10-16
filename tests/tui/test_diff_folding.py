import asyncio
from typing import Any, Literal

from rich.console import Console

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import DiffFileDiff, DiffLine, DiffSpan, DiffUIExtra
from klaude_code.tui.components.diffs import render_structured_diff
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.display import TUIDisplay

from .test_transcript_toggle import make_envelope, patch_scrollback_writes


def _file(path: str, changed: int, change_type: Literal["add", "update", "delete"] = "update") -> DiffFileDiff:
    lines = [
        DiffLine(kind="add", new_line_no=index, spans=[DiffSpan(op="insert", text=f"line {index}")])
        for index in range(1, changed + 1)
    ]
    return DiffFileDiff(file_path=path, lines=lines, stats_add=changed, change_type=change_type)


def _plain(diff: DiffFileDiff, *, fold: bool) -> str:
    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_structured_diff(DiffUIExtra(files=[diff]), fold=fold))
    return console.export_text()


def test_folding_shows_small_edits_whole_and_previews_large_ones() -> None:
    assert "line 10" in _plain(_file("src/app.py", 10), fold=True)
    large = _plain(_file("src/app.py", 11), fold=True)
    assert "line 5" in large and "line 6" not in large and "6 more lines · Ctrl+T" in large
    assert "line 11" in _plain(_file("src/app.py", 11), fold=False)


def test_folding_hides_new_code_files_and_gives_docs_a_larger_budget() -> None:
    new_code = _plain(_file("src/new.py", 40, "add"), fold=True)
    assert "src/new.py (+40)" in new_code and "line 1" not in new_code and "40 more lines" in new_code
    assert "line 30" in _plain(_file("docs/guide.md", 30), fold=True)
    large_doc = _plain(_file("docs/guide.md", 31), fold=True)
    assert "line 15" in large_doc and "line 16" not in large_doc
    new_doc = _plain(_file("docs/new.md", 40, "add"), fold=True)
    assert "line 15" in new_doc and "line 16" not in new_doc


def test_ctrl_t_rebuilds_transcript_with_diffs_expanded(monkeypatch: Any) -> None:
    async def run() -> list[tuple[str, bool]]:
        writes = patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        result = events.ToolResultEvent(
            session_id="main",
            tool_call_id="edit-1",
            tool_name=tools.EDIT,
            result="ok",
            status="success",
            ui_extra=DiffUIExtra(files=[_file("src/app.py", 20)]),
        )
        try:
            await display.consume_envelope(make_envelope(events.TaskStartEvent(session_id="main")))
            await display.consume_envelope(make_envelope(result))
            await display.consume_envelope(make_envelope(events.ToggleDiffDetailEvent(session_id="main")))
            assert display.compact_transcript is True
        finally:
            await display.stop()
        return writes

    writes = asyncio.run(run())
    expanded, cleared = writes[-1]
    assert cleared and "line 20" in expanded and "more lines" not in expanded
