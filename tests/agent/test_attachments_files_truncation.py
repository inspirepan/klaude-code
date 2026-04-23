"""Tests for <system-reminder> truncation in agent/attachments/files.py."""

from __future__ import annotations

import asyncio
from pathlib import Path

from klaude_code.agent.attachments import files as files_attachment
from klaude_code.agent.attachments.state import build_attachment_tool_context
from klaude_code.const import ATTACHMENT_DIFF_MAX_LINES, ATTACHMENT_DIFF_SOURCE_MAX_BYTES
from klaude_code.protocol import message
from klaude_code.protocol.models import FileStatus
from klaude_code.session.session import Session
from klaude_code.tool.file.read_tool import ReadTool


def test_compute_diff_snippet_truncates_long_diff_with_read_hint(tmp_path: Path) -> None:
    file_path = tmp_path / "big.txt"

    old_lines = [f"old line {i}" for i in range(3 * ATTACHMENT_DIFF_MAX_LINES)]
    new_lines = [f"new line {i}" for i in range(3 * ATTACHMENT_DIFF_MAX_LINES)]

    snippet = files_attachment._compute_diff_snippet(  # pyright: ignore[reportPrivateUsage]
        "\n".join(old_lines),
        "\n".join(new_lines),
        str(file_path),
    )

    visible_lines = snippet.splitlines()
    # Truncation notice lives at the tail, so the head must be at least the line cap.
    assert sum(1 for line in visible_lines if line.startswith(("  ", "       "))) <= ATTACHMENT_DIFF_MAX_LINES
    assert "more diff lines omitted" in snippet
    assert "Read tool with offset/limit" in snippet
    assert str(file_path) in snippet


def test_compute_diff_snippet_skips_when_source_too_large(tmp_path: Path) -> None:
    file_path = tmp_path / "huge.html"

    # Produce content where old+new comfortably exceeds the skip threshold.
    half = ATTACHMENT_DIFF_SOURCE_MAX_BYTES
    old_content = "a" * half
    new_content = "b" * half

    snippet = files_attachment._compute_diff_snippet(  # pyright: ignore[reportPrivateUsage]
        old_content,
        new_content,
        str(file_path),
    )

    assert "diff skipped" in snippet
    assert str(file_path) in snippet
    assert "Read tool with offset/limit" in snippet
    # The bulk content must not leak into the reminder.
    assert "a" * 1024 not in snippet
    assert "b" * 1024 not in snippet
    assert len(snippet) < 1024


def test_compute_diff_snippet_skips_when_utf8_bytes_exceed_limit(tmp_path: Path) -> None:
    file_path = tmp_path / "utf8.txt"

    # Each Chinese character uses 3 bytes in UTF-8, so the byte budget is
    # exceeded even though the Python character count stays below the limit.
    chars_per_side = ATTACHMENT_DIFF_SOURCE_MAX_BYTES // 4
    old_content = "旧" * chars_per_side
    new_content = "新" * chars_per_side

    snippet = files_attachment._compute_diff_snippet(  # pyright: ignore[reportPrivateUsage]
        old_content,
        new_content,
        str(file_path),
    )

    assert "diff skipped" in snippet
    assert "Read tool with offset/limit" in snippet
    assert str(file_path) in snippet


def test_compute_diff_snippet_small_diff_unchanged(tmp_path: Path) -> None:
    file_path = tmp_path / "small.txt"
    snippet = files_attachment._compute_diff_snippet(  # pyright: ignore[reportPrivateUsage]
        "hello\nworld\n",
        "hello\nmars\n",
        str(file_path),
    )
    assert "Use the Read tool" not in snippet
    assert "diff skipped" not in snippet
    assert "mars" in snippet


def test_file_changed_externally_attachment_caps_reminder_size(
    tmp_path: Path, isolated_home: Path
) -> None:
    del isolated_home

    async def _test() -> None:
        file_path = tmp_path / "page.html"

        # Sized to stay under ReadTool's internal caps (READ_GLOBAL_LINE_CAP=2000,
        # READ_MAX_CHARS=50000) so that cached_content gets populated after the
        # Read dispatched inside file_changed_externally_attachment. Every line
        # is different, so the resulting diff is well over ATTACHMENT_DIFF_MAX_LINES.
        old_content = "\n".join(f"old-{i:04d}" for i in range(1500))
        new_content = "\n".join(f"new-{i:04d}" for i in range(1500))

        file_path.write_text(new_content, encoding="utf-8")

        session = Session(work_dir=tmp_path)
        session.file_tracker[str(file_path)] = FileStatus(
            mtime=0.0,
            content_sha256="deadbeef",
            cached_content=old_content,
            read_complete=True,
        )

        reminder = await files_attachment.file_changed_externally_attachment(session)
        assert reminder is not None
        text = message.join_text_parts(reminder.parts)

        # In the regression case this reminder was ~1.85 MB. With the line cap
        # in place the diff + notice should be a small fraction of the source.
        assert len(text) < 200 * 1024, f"reminder unexpectedly large: {len(text)} bytes"
        assert "more diff lines omitted" in text
        assert "Read tool with offset/limit" in text
        assert str(file_path) in text

        read_result = await ReadTool.call_with_args(
            ReadTool.ReadArguments(file_path=str(file_path), offset=1, limit=2),
            build_attachment_tool_context(session),
        )
        assert read_result.status == "success"
        assert "File unchanged since last read" not in read_result.output_text
        assert "new-0000" in read_result.output_text

    asyncio.run(_test())
