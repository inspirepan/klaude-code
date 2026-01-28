from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from prompt_toolkit.document import Document

from klaude_code.tui.input.completers import _AtFilesCompleter, _CmdResult  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    import pytest


def test_at_files_completer_returns_git_candidates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure non-empty git candidates are not accidentally dropped.

    This protects against a control-flow bug where `_complete_paths` would
    return `[]` even after git produced matches.
    """

    # Create a tiny workspace to avoid relying on the developer's real cwd.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]

    def fake_git_paths_for_keyword(cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        assert cwd == tmp_path
        assert keyword_norm == "src"
        assert max_results > 0
        # Include a directory (trailing slash) and a file.
        return ["src/", "src/main.py"], False

    # Avoid invoking real git/fd/rg.
    monkeypatch.setattr(completer, "_git_paths_for_keyword", fake_git_paths_for_keyword)
    monkeypatch.setattr(completer, "_has_cmd", lambda _name: False)  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]

    doc = Document(text="@src", cursor_position=len("@src"))
    completions = list(completer.get_completions(doc, cast(Any, None)))

    assert completions
    inserted = {c.text for c in completions}
    assert "@src/ " in inserted or "@src/main.py " in inserted


def test_at_files_completer_preserves_dotfile_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure dotfile paths like '.claude/' are not mangled.

    Regression test: using `lstrip("./")` would incorrectly turn
    '.claude/...' into 'claude/...'.
    """

    (tmp_path / ".claude" / "skills" / "publish" / "scripts").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "publish" / "scripts" / "update_changelog.py").write_text(
        "print('ok')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]

    def fake_git_paths_for_keyword(cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        assert cwd == tmp_path
        assert keyword_norm == ".c"
        assert max_results > 0
        return [
            ".claude/skills/publish/scripts/update_changelog.py",
            "./.claude/skills/publish/scripts/update_changelog.py",
        ], False

    monkeypatch.setattr(completer, "_git_paths_for_keyword", fake_git_paths_for_keyword)
    monkeypatch.setattr(completer, "_has_cmd", lambda _name: False)  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]

    doc = Document(text="@.c", cursor_position=len("@.c"))
    completions = list(completer.get_completions(doc, cast(Any, None)))

    assert completions
    inserted = {c.text for c in completions}
    assert "@.claude/skills/publish/scripts/update_changelog.py " in inserted


def test_at_files_completer_formats_display_labels() -> None:
    """Display labels show basename (with trailing slash for directories), padded for alignment."""

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]

    suggestions = [
        "src/klaude_code/ui/modes/repl/completers.py",
        "docs/",
        "pyproject.toml",
    ]

    # Calculate align_width as the completer does
    align_width = completer._display_align_width(suggestions)  # pyright: ignore[reportPrivateUsage]

    labels = [
        completer._format_display_label(suggestion, align_width)  # pyright: ignore[reportPrivateUsage]
        for suggestion in suggestions
    ]

    # Labels show basename (with trailing slash for directories), stripped of padding
    assert labels[0].strip() == "completers.py"
    assert labels[1].strip() == "docs/"
    assert labels[2].strip() == "pyproject.toml"

    # All labels should have the same length (aligned)
    assert len(labels[0]) == len(labels[1]) == len(labels[2])


def test_git_paths_for_keyword_includes_all_tools_dirs_even_when_many_files_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ensure we don't lose later */tools/ directories due to early scan truncation.

    Regression case:
    - There are many matching files under one tools directory early in git path order.
    - Other */tools/ directories exist later.

    We still want all those tools directories to be eligible completion candidates.
    """

    monkeypatch.chdir(tmp_path)
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]

    # Avoid depending on a real git repo.
    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: tmp_path)  # pyright: ignore[reportUnknownArgumentType,reportUnknownLambdaType]

    git_lines = [f"auxiliary/tools/file_{i}.py" for i in range(200)] + [
        "image/tools/x.py",
        "video/tools/y.py",
        "three_d/tools/z.py",
    ]

    def fake_run_cmd(cmd: list[str], cwd: Path | None = None, *, timeout_sec: float) -> _CmdResult:
        assert cmd[:2] == ["git", "ls-files"]
        return _CmdResult(True, git_lines)

    monkeypatch.setattr(completer, "_run_cmd", fake_run_cmd)

    candidates, truncated = completer._git_paths_for_keyword(tmp_path, "tools", max_results=5)  # pyright: ignore[reportPrivateUsage]

    assert not truncated
    assert {
        "auxiliary/tools/",
        "image/tools/",
        "video/tools/",
        "three_d/tools/",
    }.issubset(set(candidates))
