from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from prompt_toolkit.document import Document

from klaude_code.ui.modes.repl.completers import _AtFilesCompleter  # pyright: ignore[reportPrivateUsage]

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
