from pathlib import Path

import pytest

from klaude_code.core import memory


def test_load_auto_memory_without_truncation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "MEMORY.md"
    file_path.write_text("line1\nline2\n", encoding="utf-8")

    def _auto_memory_path(_work_dir: Path) -> Path:
        return file_path

    monkeypatch.setattr(memory, "get_auto_memory_path", _auto_memory_path)

    loaded = memory.load_auto_memory(work_dir=tmp_path)

    assert loaded is not None
    assert loaded.path == str(file_path)
    assert loaded.instruction == "auto memory, persisted across sessions"
    assert loaded.content == "line1\nline2\n"


def test_load_auto_memory_with_truncation_notice(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lines = [f"line {i}" for i in range(1, memory.AUTO_MEMORY_MAX_LINES + 6)]
    file_path = tmp_path / "MEMORY.md"
    file_path.write_text("\n".join(lines), encoding="utf-8")

    def _auto_memory_path(_work_dir: Path) -> Path:
        return file_path

    monkeypatch.setattr(memory, "get_auto_memory_path", _auto_memory_path)

    loaded = memory.load_auto_memory(work_dir=tmp_path)

    assert loaded is not None
    assert loaded.instruction == (
        "auto memory, persisted across sessions "
        f"(truncated to first {memory.AUTO_MEMORY_MAX_LINES} lines from {len(lines)} total lines)"
    )
    assert len(loaded.content.splitlines()) == memory.AUTO_MEMORY_MAX_LINES
    assert loaded.content.splitlines()[-1] == f"line {memory.AUTO_MEMORY_MAX_LINES}"


def test_get_existing_memory_files_includes_git_root_memories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    repo_root = tmp_path / "repo"
    work_dir = repo_root / "apps" / "service"
    work_dir.mkdir(parents=True)
    (repo_root / ".git").mkdir()

    root_agents = repo_root / "AGENTS.md"
    root_claude = repo_root / "CLAUDE.md"
    root_agents.write_text("root agents", encoding="utf-8")
    root_claude.write_text("root claude", encoding="utf-8")

    root_claude_dir_file = repo_root / ".claude" / "CLAUDE.md"
    root_claude_dir_file.parent.mkdir()
    root_claude_dir_file.write_text("repo .claude", encoding="utf-8")

    root_agents_dir_file = repo_root / ".agents" / "AGENT.md"
    root_agents_dir_file.parent.mkdir()
    root_agents_dir_file.write_text("repo .agents", encoding="utf-8")

    result = memory.get_existing_memory_files(work_dir=work_dir)

    assert set(result["project"]) == {
        str(root_agents),
        str(root_claude_dir_file),
        str(root_agents_dir_file),
    }
    assert str(root_claude) not in result["project"]
    assert result["user"] == []


def test_get_existing_memory_files_does_not_scan_parent_without_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    parent_dir = tmp_path / "not-a-git-root"
    work_dir = parent_dir / "service"
    work_dir.mkdir(parents=True)

    parent_agents = parent_dir / "AGENTS.md"
    parent_agents.write_text("parent agents", encoding="utf-8")

    work_agents = work_dir / "AGENTS.md"
    work_agents.write_text("work agents", encoding="utf-8")

    result = memory.get_existing_memory_files(work_dir=work_dir)

    assert result["project"] == [str(work_agents)]
    assert result["user"] == []
