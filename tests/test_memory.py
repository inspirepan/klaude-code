from pathlib import Path

import pytest

from klaude_code.core import memory


def test_load_auto_memory_without_truncation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "MEMORY.md"
    file_path.write_text("line1\nline2\n", encoding="utf-8")
    monkeypatch.setattr(memory, "get_auto_memory_path", lambda: file_path)

    loaded = memory.load_auto_memory()

    assert loaded is not None
    assert loaded.path == str(file_path)
    assert loaded.instruction == "auto memory, persisted across sessions"
    assert loaded.content == "line1\nline2\n"


def test_load_auto_memory_with_truncation_notice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lines = [f"line {i}" for i in range(1, memory.AUTO_MEMORY_MAX_LINES + 6)]
    file_path = tmp_path / "MEMORY.md"
    file_path.write_text("\n".join(lines), encoding="utf-8")
    monkeypatch.setattr(memory, "get_auto_memory_path", lambda: file_path)

    loaded = memory.load_auto_memory()

    assert loaded is not None
    assert loaded.instruction == (
        "auto memory, persisted across sessions "
        f"(truncated to first {memory.AUTO_MEMORY_MAX_LINES} lines from {len(lines)} total lines)"
    )
    assert len(loaded.content.splitlines()) == memory.AUTO_MEMORY_MAX_LINES
    assert loaded.content.splitlines()[-1] == f"line {memory.AUTO_MEMORY_MAX_LINES}"
