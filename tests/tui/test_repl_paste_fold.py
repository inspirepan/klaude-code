from __future__ import annotations

import os
import time
from pathlib import Path

from klaude_code.tui.input.paste import PASTE_FILE_RETENTION_SECONDS, PasteBufferState


def test_store_saves_twenty_lines_immediately(tmp_path: Path) -> None:
    state = PasteBufferState()
    text = "\n".join([f"line {i}" for i in range(20)])

    marker = state.store(text, tmp_path)

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert marker == f"[paste #1 +20 lines: {files[0].resolve()}]"
    assert files[0].read_text(encoding="utf-8") == text


def test_store_saves_two_thousand_chars_immediately(tmp_path: Path) -> None:
    state = PasteBufferState()
    text = "x" * 2000

    marker = state.store(text, tmp_path)

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert marker == f"[paste #1 2000 chars: {files[0].resolve()}]"


def test_store_keeps_small_paste_inline(tmp_path: Path) -> None:
    state = PasteBufferState()

    marker = state.store("x" * 1999, tmp_path)

    assert marker is None
    assert list(tmp_path.iterdir()) == []


def test_store_uses_short_default_directory(isolated_home: Path) -> None:
    state = PasteBufferState()

    marker = state.store("x" * 2000)

    assert marker is not None
    files = list((isolated_home / ".klaude" / "tmp").iterdir())
    assert len(files) == 1


def test_store_prunes_stale_paste_files(tmp_path: Path) -> None:
    stale_file = tmp_path / "paste-stale.txt"
    stale_file.write_text("stale", encoding="utf-8")
    stale_time = time.time() - PASTE_FILE_RETENTION_SECONDS - 1
    os.utime(stale_file, (stale_time, stale_time))

    PasteBufferState().store("x" * 2000, tmp_path)

    assert not stale_file.exists()


def test_expand_replaces_marker_with_saved_file_reference(tmp_path: Path) -> None:
    state = PasteBufferState()
    text = "x" * 2000
    marker = state.store(text, tmp_path)
    assert marker is not None

    expanded = state.expand_markers(f"prefix {marker} suffix")

    paste_file = next(tmp_path.iterdir()).resolve()
    assert expanded == (
        "prefix \n<system-reminder>The user pasted a large text block. "
        f"It was saved to {paste_file}. Use the Read tool to inspect it.</system-reminder>\n suffix"
    )
    assert text not in expanded


def test_expand_keeps_unknown_marker_intact() -> None:
    state = PasteBufferState()
    out = state.expand_markers("[paste #999 +12 lines]")
    assert out == "[paste #999 +12 lines]"
