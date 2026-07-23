from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from prompt_toolkit.document import Document

from klaude_code.tui.input.completers import (  # pyright: ignore[reportPrivateUsage]
    _AtFilesCompleter,
    _CmdResult,
    path_matches_query,
)

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

    # Avoid invoking the real Git command.
    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(completer, "_git_paths_for_keyword", fake_git_paths_for_keyword)

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

    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(completer, "_git_paths_for_keyword", fake_git_paths_for_keyword)

    doc = Document(text="@.c", cursor_position=len("@.c"))
    completions = list(completer.get_completions(doc, cast(Any, None)))

    assert completions
    inserted = {c.text for c in completions}
    assert "@.claude/skills/publish/scripts/update_changelog.py " in inserted


@pytest.mark.parametrize(
    ("text", "should_match"),
    [
        ("请看@src", True),
        ("これは@src", True),
        ("email@src", False),
    ],
)
def test_at_files_completer_allows_cjk_without_space(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    text: str,
    should_match: bool,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    call_count = 0

    def fake_git_paths_for_keyword(cwd: Path, keyword_norm: str, *, max_results: int) -> tuple[list[str], bool]:
        nonlocal call_count
        call_count += 1
        assert cwd == tmp_path
        assert keyword_norm == "src"
        assert max_results > 0
        return ["src/", "src/main.py"], False

    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(completer, "_git_paths_for_keyword", fake_git_paths_for_keyword)

    doc = Document(text=text, cursor_position=len(text))
    completions = list(completer.get_completions(doc, cast(Any, None)))
    inserted = {c.text for c in completions}

    assert ("@src/ " in inserted or "@src/main.py " in inserted) is should_match
    assert call_count == (1 if should_match else 0)


def test_at_files_completer_formats_display_labels() -> None:
    """Display labels show full path with dim directory prefix."""

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]

    suggestions = [
        "src/klaude_code/ui/modes/repl/completers.py",
        "docs/",
        "pyproject.toml",
    ]

    labels = [
        completer._format_display_label(s)  # pyright: ignore[reportPrivateUsage]
        for s in suggestions
    ]

    def _plain(ft: object) -> str:
        items = cast("list[tuple[str, str]]", ft)
        return "".join(seg[1] for seg in items)

    # Each label is a FormattedText (list of (style, text[, handler]) tuples).
    # The first suggestion should have a dim directory prefix and a basename segment.
    assert _plain(labels[0]) == "src/klaude_code/ui/modes/repl/completers.py"

    # Directory suggestion includes trailing slash
    assert _plain(labels[1]) == "docs/"

    # Root-level file has no directory prefix
    assert _plain(labels[2]) == "pyproject.toml"


def test_complete_paths_falls_back_to_python_scan_with_files_and_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The command-free fallback preserves recursive substring matching."""

    (tmp_path / "src" / "ToolBox").mkdir(parents=True)
    (tmp_path / "src" / "ToolBox" / "helper.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "my_tool.py").write_text("", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    monkeypatch.chdir(tmp_path)

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: None)

    results = completer._complete_paths(tmp_path, "TOOL")  # pyright: ignore[reportPrivateUsage]

    assert "src/ToolBox/" in results
    assert "src/ToolBox/helper.py" in results
    assert "src/my_tool.py" in results
    assert all("docs" not in result for result in results)


def test_complete_paths_does_not_scan_filesystem_after_empty_git_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(completer, "_git_paths_for_keyword", lambda *_args, **_kwargs: ([], False))

    def fail_scan(*_args: object, **_kwargs: object) -> tuple[list[str], bool]:
        raise AssertionError("Git misses must not trigger a full filesystem scan")

    monkeypatch.setattr(completer, "_python_paths_for_keyword", fail_scan)

    assert completer._complete_paths(tmp_path, "missing") == []  # pyright: ignore[reportPrivateUsage]


def test_python_scan_excludes_dependency_and_vcs_directories(tmp_path: Path) -> None:
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    for dirname in (".git", ".venv", "node_modules"):
        directory = tmp_path / dirname
        directory.mkdir()
        (directory / "target.py").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "target.py").write_text("", encoding="utf-8")

    results, truncated = completer._python_paths_for_keyword(  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        "target",
        max_results=20,
    )

    assert results == ["src/target.py"]
    assert not truncated


def test_python_scan_bounds_work_by_elapsed_time(tmp_path: Path) -> None:
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    completer._filesystem_scan_timeout_sec = 0.0  # pyright: ignore[reportPrivateUsage]
    (tmp_path / "file.txt").write_text("", encoding="utf-8")

    results, truncated = completer._python_paths_for_keyword(  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        "missing",
        max_results=1,
    )

    assert results == []
    assert truncated


def test_python_scan_bounds_work_by_entry_count(tmp_path: Path) -> None:
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    completer._filesystem_scan_max_entries = 1  # pyright: ignore[reportPrivateUsage]
    (tmp_path / "first.txt").write_text("", encoding="utf-8")
    (tmp_path / "second.txt").write_text("", encoding="utf-8")

    results, truncated = completer._python_paths_for_keyword(  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        "missing",
        max_results=1,
    )

    assert results == []
    assert truncated


def test_filter_and_format_preserves_relevance_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Visible paths stay ahead of hidden/test paths, then favor basename hits."""

    paths = [
        ".hidden/tool.py",
        "tests/tool.py",
        "src/tooling/helper.py",
        "src/deep/tool.py",
        "tool.py",
    ]
    for rel in paths:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    results = completer._filter_and_format(paths, tmp_path, "tool")  # pyright: ignore[reportPrivateUsage]

    assert results == [
        "tool.py",
        "src/deep/tool.py",
        "src/tooling/helper.py",
        "tests/tool.py",
        ".hidden/tool.py",
    ]


def test_path_fuzzy_match_supports_cross_segment_subsequences() -> None:
    assert path_matches_query("crates/workspace/src/file_system/fuzzy.rs", "fsfz")
    assert path_matches_query("src/components/ToolBlock.tsx", "sctb")
    assert not path_matches_query("src/main.py", "zzzz")
    assert not path_matches_query("src/zzabcdefghijklmnopv.py", "av")


def test_path_fuzzy_match_handles_unicode_lowercase_expansion() -> None:
    assert path_matches_query("İx.txt", "ix")


def test_filter_and_format_prefers_exact_matches_over_fuzzy_matches(tmp_path: Path) -> None:
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    paths = ["src/configuration.py", "src/cfg.py", "src/config/file_generator.py"]

    results = completer._filter_and_format(paths, tmp_path, "cfg")  # pyright: ignore[reportPrivateUsage]

    assert results[0] == "src/cfg.py"
    assert set(results) == set(paths)


def test_python_scan_returns_fuzzy_path_matches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "src" / "file_system" / "fuzzy.py"
    target.parent.mkdir(parents=True)
    target.write_text("", encoding="utf-8")

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: None)

    assert "src/file_system/fuzzy.py" in completer._complete_paths(  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        "fsfz",
    )


def test_python_scan_does_not_overlap(tmp_path: Path) -> None:
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    assert completer._path_search_lock.acquire(blocking=False)  # pyright: ignore[reportPrivateUsage]
    try:
        results, truncated = completer._python_paths_for_keyword(  # pyright: ignore[reportPrivateUsage]
            tmp_path,
            "src",
            max_results=20,
        )
    finally:
        completer._path_search_lock.release()  # pyright: ignore[reportPrivateUsage]

    assert results == []
    assert truncated


def test_empty_at_fragment_lists_only_immediate_entries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "src" / "nested" / "file.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / ".hidden").write_text("", encoding="utf-8")
    for dirname in (".git", ".venv", "node_modules"):
        (tmp_path / dirname).mkdir()
    monkeypatch.chdir(tmp_path)

    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    completions = list(completer.get_completions(Document(text="@", cursor_position=1), cast(Any, None)))
    inserted = [completion.text for completion in completions]

    assert inserted == ["@src/ ", "@README.md ", "@tests/ ", "@.hidden "]
    assert all("nested" not in completion for completion in inserted)


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
        assert cmd[:4] == ["git", "-c", "core.quotePath=false", "ls-files"]
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


def test_git_paths_for_keyword_returns_cross_segment_fuzzy_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: tmp_path)
    git_lines = [
        "src/main.py",
        "crates/workspace/src/file_system/fuzzy.rs",
    ]

    def fake_run_cmd(cmd: list[str], cwd: Path | None = None, *, timeout_sec: float) -> _CmdResult:
        del cwd, timeout_sec
        if "--recurse-submodules" in cmd:
            return _CmdResult(True, [])
        return _CmdResult(True, git_lines)

    monkeypatch.setattr(completer, "_run_cmd", fake_run_cmd)

    candidates, truncated = completer._git_paths_for_keyword(  # pyright: ignore[reportPrivateUsage]
        tmp_path,
        "fsfz",
        max_results=10,
    )

    assert "crates/workspace/src/file_system/fuzzy.rs" in candidates
    assert not truncated


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
        assert cmd[:4] == ["git", "-c", "core.quotePath=false", "ls-files"]
        return _CmdResult(True, git_lines)

    monkeypatch.setattr(completer, "_run_cmd", fake_run_cmd)

    broad = completer._complete_paths(tmp_path, "tool")  # pyright: ignore[reportPrivateUsage]
    refined = completer._complete_paths(tmp_path, "toolblock")  # pyright: ignore[reportPrivateUsage]

    assert "web/src/components/messages/ToolBlock.tsx" not in broad
    assert refined == ["web/src/components/messages/ToolBlock.tsx"]


def test_git_paths_for_keyword_decodes_git_quoted_cjk_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    completer = _AtFilesCompleter()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(completer, "_get_git_repo_root", lambda _cwd: tmp_path)  # pyright: ignore[reportUnknownArgumentType,reportUnknownLambdaType]

    git_lines = [
        '"cases/wechat-longform/case-1-\\345\\206\\234\\350\\241\\214/source.txt"',
        '"cases/wechat-longform/case-3-\\351\\253\\230\\345\\216\\237/source.txt"',
    ]

    def fake_run_cmd(cmd: list[str], cwd: Path | None = None, *, timeout_sec: float) -> _CmdResult:
        assert cmd[:4] == ["git", "-c", "core.quotePath=false", "ls-files"]
        return _CmdResult(True, git_lines)

    monkeypatch.setattr(completer, "_run_cmd", fake_run_cmd)

    candidates, truncated = completer._git_paths_for_keyword(tmp_path, "case", max_results=10)  # pyright: ignore[reportPrivateUsage]

    assert not truncated
    assert "cases/wechat-longform/case-1-农行/source.txt" in candidates
    assert "cases/wechat-longform/case-3-高原/source.txt" in candidates
