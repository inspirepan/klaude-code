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
    """Display labels show full path with dim directory prefix and highlighted keyword."""

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]

    suggestions = [
        "src/klaude_code/ui/modes/repl/completers.py",
        "docs/",
        "pyproject.toml",
    ]

    labels = [
        completer._format_display_label(s, keyword="comp")  # pyright: ignore[reportPrivateUsage]
        for s in suggestions
    ]

    def _plain(ft: object) -> str:
        return "".join(seg[1] for seg in ft)  # type: ignore[index]

    # Each label is a FormattedText (list of (style, text[, handler]) tuples).
    # The first suggestion should have a dim directory prefix and a basename segment.
    assert _plain(labels[0]) == "src/klaude_code/ui/modes/repl/completers.py"

    # Directory suggestion includes trailing slash
    assert _plain(labels[1]) == "docs/"

    # Root-level file has no directory prefix
    assert _plain(labels[2]) == "pyproject.toml"


def test_at_files_completer_display_label_highlights_keyword() -> None:
    """Keyword match in the path is highlighted with a special style."""
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]

    label = completer._format_display_label("src/very_long_tools_filename.py", keyword="tools")  # pyright: ignore[reportPrivateUsage]

    # The label should contain a highlighted segment for "tools"
    styles = [seg[0] for seg in label]  # type: ignore[index]
    texts = [seg[1] for seg in label]  # type: ignore[index]
    full_text = "".join(texts)
    assert full_text == "src/very_long_tools_filename.py"

    # At least one segment should have the highlight style
    assert any("bg:" in s for s in styles), f"Expected highlight style in {styles}"


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

    assert truncated
    assert {
        "auxiliary/tools/",
        "image/tools/",
        "video/tools/",
        "three_d/tools/",
    }.issubset(set(candidates))


def test_complete_paths_refines_past_incomplete_git_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A narrower query must not reuse an incomplete cached git result set."""

    toolblock = tmp_path / "web" / "src" / "components" / "messages" / "ToolBlock.tsx"
    toolblock.parent.mkdir(parents=True)
    toolblock.write_text("export {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    completer = _AtFilesCompleter(max_results=5)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: tmp_path)  # pyright: ignore[reportUnknownArgumentType,reportUnknownLambdaType]

    git_lines = [f"src/tooling/tool_{i}.py" for i in range(20)] + ["web/src/components/messages/ToolBlock.tsx"]

    def fake_run_cmd(cmd: list[str], cwd: Path | None = None, *, timeout_sec: float) -> _CmdResult:
        assert cmd[:2] == ["git", "ls-files"]
        return _CmdResult(True, git_lines)

    monkeypatch.setattr(completer, "_run_cmd", fake_run_cmd)

    broad = completer._complete_paths(tmp_path, "tool")  # pyright: ignore[reportPrivateUsage]
    refined = completer._complete_paths(tmp_path, "toolblock")  # pyright: ignore[reportPrivateUsage]

    assert "web/src/components/messages/ToolBlock.tsx" not in broad
    assert refined == ["web/src/components/messages/ToolBlock.tsx"]
