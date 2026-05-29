"""Characterization tests for ReadTool (G6).

These lock in the CURRENT observable behavior of
``klaude_code.tool.file.read_tool.ReadTool`` so that a later refactor can be
proven behavior-preserving. They assert what the code currently DOES, not what
it arguably should do.

Covered:
- plain text line numbering (golden) and per-line / total-char truncation
- notebook (.ipynb) structured rendering, including output cells
- image inline read (returns ImageFilePart + tracker hash)
- PDF read path (pdfplumber NOT installed -> install-instructions error)
- read dedup (same file twice -> FILE_UNCHANGED_STUB)
- the @311 invalid-arguments error path
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from klaude_code.prompts.messages import FILE_UNCHANGED_STUB
from klaude_code.protocol import message
from klaude_code.protocol.models import ImageUIExtra, ReadPreviewUIExtra
from klaude_code.session.session import Session
from klaude_code.tool import ReadTool, build_todo_context
from klaude_code.tool.core.context import ToolContext

# 1x1 transparent PNG (same fixture used by tests/agent/test_read_edit.py).
_TINY_PNG_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _make_context(work_dir: Path) -> tuple[Session, ToolContext]:
    session = Session(work_dir=work_dir)
    context = ToolContext(
        file_tracker=session.file_tracker,
        todo_context=build_todo_context(session),
        session_id=session.id,
        work_dir=work_dir.resolve(),
        file_change_summary=session.file_change_summary,
    )
    return session, context


# --------------------------------------------------------------------------
# 1. Plain text: line numbering / truncation
# --------------------------------------------------------------------------


def test_read_plain_text_line_numbering_golden(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "basic.txt").resolve())
    Path(file_path).write_text("alpha\nbeta\ngamma\n", encoding="utf-8")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "success"
    # The exact line-numbering format: 6-width right-aligned number + arrow.
    assert res.output_text == "     1→alpha\n     2→beta\n     3→gamma"
    # No UI preview extra for full reads from line 1.
    assert res.ui_extra is None


def test_read_plain_text_records_sha256_in_tracker(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    session, context = _make_context(tmp_path)
    file_path = str((tmp_path / "tracked.txt").resolve())
    raw = "line1\nline2\nline3\n"
    Path(file_path).write_text(raw, encoding="utf-8")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "success"
    status = session.file_tracker.get(file_path)
    assert status is not None
    assert status.content_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert status.read_complete is True


def test_read_per_line_char_truncation(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "longline.txt").resolve())
    # READ_CHAR_LIMIT_PER_LINE is 2000; 2100 chars -> 100 truncated.
    Path(file_path).write_text("x" * 2100 + "\n", encoding="utf-8")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "success"
    assert "1→" in (res.output_text or "")
    assert "more 100 characters in this line are truncated" in (res.output_text or "")


def test_read_line_cap_truncation(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "many.txt").resolve())
    # 5000 short lines: the 2000-line cap (READ_GLOBAL_LINE_CAP) is hit before the
    # 50000-char total cap, so the line-limit truncation message is emitted.
    with open(file_path, "w", encoding="utf-8") as f:
        for i in range(5000):
            f.write(f"line{i}\n")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "success"
    out = res.output_text or ""
    assert "3000 more lines truncated due to 2000 line limit" in out
    assert "file has 5000 lines total" in out
    assert "use offset/limit to read other parts" in out


def test_read_total_char_limit_truncation(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "big.txt").resolve())
    # Long lines (40 chars each) so the 50000-char total cap is reached before the
    # 2000-line cap.
    with open(file_path, "w", encoding="utf-8") as f:
        for _ in range(4000):
            f.write("x" * 40 + "\n")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "success"
    out = res.output_text or ""
    assert "more lines truncated due to 50000 char limit" in out
    assert "file has 4000 lines total" in out
    assert "use offset/limit to read other parts" in out


def test_read_offset_emits_preview_ui_extra(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "offset.txt").resolve())
    with open(file_path, "w", encoding="utf-8") as f:
        for i in range(1, 21):
            f.write(f"row{i}\n")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path, "offset": 5, "limit": 10}), context))

    assert res.status == "success"
    # First selected line is line 5.
    assert "     5→row5" in (res.output_text or "")
    # Reading from the middle produces a compact preview (READ_PARTIAL_PREVIEW_MAX_LINES = 3).
    assert isinstance(res.ui_extra, ReadPreviewUIExtra)
    assert len(res.ui_extra.lines) == 3
    assert res.ui_extra.lines[0].line_no == 5
    assert res.ui_extra.remaining_lines == 7


def test_read_offset_beyond_eof_warns(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "short.txt").resolve())
    Path(file_path).write_text("only\ntwo\n", encoding="utf-8")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path, "offset": 100}), context))

    assert res.status == "success"
    out = res.output_text or ""
    assert "the file exists but is shorter than the provided offset (100)" in out
    assert "The file has 2 lines." in out


# --------------------------------------------------------------------------
# 2. Notebook (.ipynb)
# --------------------------------------------------------------------------


def test_read_notebook_structured_output(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "nb.ipynb").resolve())
    notebook = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Title\n", "intro"]},
            {
                "cell_type": "code",
                "source": ["print('hi')\n"],
                "outputs": [
                    {"output_type": "stream", "text": ["hi\n"]},
                    {"output_type": "execute_result", "data": {"text/plain": ["42"]}},
                ],
            },
        ],
        "metadata": {},
        "nbformat": 4,
    }
    Path(file_path).write_text(json.dumps(notebook), encoding="utf-8")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "success"
    out = res.output_text or ""
    assert out.startswith("[Notebook] nb.ipynb")
    assert "--- Cell 1 [markdown] ---\n# Title\nintro" in out
    assert "--- Cell 2 [code] ---\nprint('hi')" in out
    assert "[output]\nhi\n" in out
    assert "[output]\n42" in out


def test_read_notebook_malformed_json_error(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "bad.ipynb").resolve())
    Path(file_path).write_text("{not valid json", encoding="utf-8")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "error"
    assert (res.output_text or "").startswith("<tool_use_error>Failed to read notebook:")


# --------------------------------------------------------------------------
# 3. Image
# --------------------------------------------------------------------------


def test_read_image_inline_success(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    session, context = _make_context(tmp_path)
    file_path = str((tmp_path / "tiny.png").resolve())
    image_bytes = base64.b64decode(_TINY_PNG_BASE64)
    Path(file_path).write_bytes(image_bytes)

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "success"
    assert res.parts
    part = res.parts[0]
    assert isinstance(part, message.ImageFilePart)
    assert part.frozen is True
    assert Path(part.file_path).exists()
    assert "[image] tiny.png" in (res.output_text or "")
    assert isinstance(res.ui_extra, ImageUIExtra)
    # Tracker stores the sha256 of the original image bytes.
    status = session.file_tracker.get(file_path)
    assert status is not None
    assert status.content_sha256 == hashlib.sha256(image_bytes).hexdigest()


def test_read_image_too_large_error(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "large.png").resolve())
    # READ_MAX_IMAGE_BYTES is 64 MiB.
    Path(file_path).write_bytes(b"0" * (64 * 1024 * 1024 + 1))

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "error"
    assert "maximum supported size (64.00MB)" in (res.output_text or "")


# --------------------------------------------------------------------------
# 4. PDF (pdfplumber is NOT a declared dependency -> ImportError branch)
# --------------------------------------------------------------------------


def test_read_pdf_without_pdfplumber_returns_install_instructions(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    try:
        import pdfplumber  # type: ignore  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("pdfplumber is installed; this test characterizes the missing-dependency branch")

    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "doc.pdf").resolve())
    # Minimal bytes; content is irrelevant because import fails before parsing.
    Path(file_path).write_bytes(b"%PDF-1.4 stub")

    res = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))

    assert res.status == "error"
    out = res.output_text or ""
    assert "PDF files require pdfplumber" in out
    assert "uv add pdfplumber" in out
    # The error embeds an executable inline-script snippet referencing the file path.
    assert file_path in out


# --------------------------------------------------------------------------
# 5. Read dedup behavior
# --------------------------------------------------------------------------


def test_read_dedup_returns_unchanged_stub_on_second_read(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "dedup.txt").resolve())
    Path(file_path).write_text("a\nb\nc\n", encoding="utf-8")

    first = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))
    assert first.status == "success"
    assert "1→a" in (first.output_text or "")

    second = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))
    assert second.status == "success"
    assert second.output_text == FILE_UNCHANGED_STUB


def test_read_dedup_resends_when_file_changes(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "changing.txt").resolve())
    Path(file_path).write_text("first\n", encoding="utf-8")

    first = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))
    assert "1→first" in (first.output_text or "")

    # Bump mtime forward and change content so the dedup mtime check fails.
    new_mtime = os.path.getmtime(file_path) + 10
    Path(file_path).write_text("second\n", encoding="utf-8")
    os.utime(file_path, (new_mtime, new_mtime))

    second = arun(ReadTool.call(json.dumps({"file_path": file_path}), context))
    assert second.status == "success"
    assert second.output_text != FILE_UNCHANGED_STUB
    assert "1→second" in (second.output_text or "")


def test_read_dedup_not_applied_with_offset(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)
    file_path = str((tmp_path / "off.txt").resolve())
    Path(file_path).write_text("x\ny\nz\n", encoding="utf-8")

    arun(ReadTool.call(json.dumps({"file_path": file_path}), context))
    # Re-read with offset; dedup only applies for offset==1 and limit is None.
    res = arun(ReadTool.call(json.dumps({"file_path": file_path, "offset": 2}), context))

    assert res.status == "success"
    assert res.output_text != FILE_UNCHANGED_STUB
    assert "     2→y" in (res.output_text or "")


# --------------------------------------------------------------------------
# 6. Invalid-arguments error path (@311)
# --------------------------------------------------------------------------


def test_read_invalid_arguments_json(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)

    res = arun(ReadTool.call("{not json}", context))

    assert res.status == "error"
    assert (res.output_text or "").startswith("Invalid arguments:")


def test_read_arguments_missing_required_field(tmp_path: Path, isolated_home: Path) -> None:
    del isolated_home
    _, context = _make_context(tmp_path)

    # file_path is required; omitting it triggers the @311 except branch.
    res = arun(ReadTool.call(json.dumps({"offset": 1}), context))

    assert res.status == "error"
    assert (res.output_text or "").startswith("Invalid arguments:")
