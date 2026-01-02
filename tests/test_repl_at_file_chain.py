import asyncio
from pathlib import Path

import pytest
from prompt_toolkit.document import Document

from klaude_code.core.reminders import at_file_reader_reminder
from klaude_code.protocol import events, message, model
from klaude_code.session.session import Session
from klaude_code.ui.modes.repl.completers import create_repl_completer
from klaude_code.ui.renderers.developer import render_developer_message
from klaude_code.ui.renderers.user_input import AT_FILE_RENDER_PATTERN, render_user_input


def _arun(coro):  # type: ignore
    return asyncio.run(coro)  # type: ignore


def _extract_plain_text(renderable: object) -> str:
    from rich.console import Console

    console = Console(width=200, record=True)
    console.print(renderable)
    output = console.export_text(styles=False)
    return output


def test_at_files_completer_quotes_paths_with_spaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: @ completion should wrap suggestions that contain spaces in quotes.

    This test simulates typing `@` in a directory that contains a file with spaces
    in its name, and asserts that the completion text uses the @"..." form.
    """

    # Prepare a temporary working directory with files
    file_plain = tmp_path / "foo.txt"
    file_plain.write_text("plain\n", encoding="utf-8")
    file_spaced = tmp_path / "dir with spaces" / "my file.txt"
    file_spaced.parent.mkdir(parents=True, exist_ok=True)
    file_spaced.write_text("spaced\n", encoding="utf-8")

    # Run REPL completer under this directory
    monkeypatch.chdir(tmp_path)

    completer = create_repl_completer()

    # Simulate typing '@dir' and asking for completions
    # We expect a suggestion containing "dir with spaces/my file.txt" and that
    # the insertion text is quoted as @"dir with spaces/my file.txt".
    text = "@dir"
    doc = Document(text=text, cursor_position=len(text))

    completions = list(completer.get_completions(doc, complete_event=None))  # type: ignore[arg-type]
    assert completions, "Expected at least one completion for @dir"

    # Collect insertion texts for debugging and assertions
    insert_texts = {c.text for c in completions}

    # At least one completion should be quoted and contain the spaced path
    assert any('"' in t for t in insert_texts), insert_texts
    assert any("dir with spaces" in t for t in insert_texts), insert_texts
    assert any((t.startswith('@"') and t.endswith(' "')) or t.endswith('" ') for t in insert_texts), insert_texts


def test_at_file_reader_reminder_and_developer_render_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: @ patterns in user input -> reminder -> developer message render.

    The chain under test:
    - User types a message that references a file via @"..." syntax
    - at_file_reader_reminder parses and reads the file, populating at_files
    - render_developer_message renders a line mentioning the file path
    """

    # Create a file with spaces and mixed-case name
    file_path = tmp_path / "Dir With Spaces" / "ReadMe File.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("hello chain\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    # Set up a session whose last user message uses the @"..." syntax
    session = Session(work_dir=tmp_path)
    user_message = message.UserMessage(parts=message.text_parts_from_str(f'Please review @"{file_path}"'))
    session.conversation_history.append(user_message)

    # Run reminder to parse and read the file
    reminder = _arun(at_file_reader_reminder(session))
    assert reminder is not None
    assert reminder.ui_extra is not None

    at_file_items = [ui_item for ui_item in reminder.ui_extra.items if isinstance(ui_item, model.AtFileOpsUIItem)]
    assert len(at_file_items) == 1
    assert len(at_file_items[0].ops) == 1

    at_file = at_file_items[0].ops[0]
    assert at_file.path.endswith("ReadMe File.txt")
    assert "hello chain" in message.join_text_parts(reminder.parts)

    # Render developer message and ensure the path appears with the same casing
    event = events.DeveloperMessageEvent(session_id="test-session", item=reminder)
    rendered = render_developer_message(event)
    plain = _extract_plain_text(rendered)

    assert "ReadMe File.txt" in plain


def test_render_user_input_highlights_full_at_pattern() -> None:
    """render_user_input should highlight full @... or @"..." segments.

    This does not check color/style, only that the plain output still contains
    the full token text, which is a proxy that the regex slicing is correct.
    """

    content = 'Look at @src/file.py and @"dir with spaces/my file.txt" please'
    rendered = render_user_input(content)

    plain = _extract_plain_text(rendered)

    # The two @-patterns should both be present verbatim in the rendered output
    assert "@src/file.py" in plain
    assert '@"dir with spaces/my file.txt"' in plain


def test_at_file_render_pattern_ignores_mid_word_at() -> None:
    """AT_FILE_RENDER_PATTERN should not match email-like mid-word @ symbols.

    We only want to treat @ as a file reference when it appears at the
    beginning of a line or immediately after whitespace.
    """

    assert AT_FILE_RENDER_PATTERN.search("foo@bar.com") is None
    assert AT_FILE_RENDER_PATTERN.search("Contact me via foo@bar.com") is None

    # But it should still match when @ starts a token at line start or after space
    assert AT_FILE_RENDER_PATTERN.search("@src/file.py") is not None
    assert AT_FILE_RENDER_PATTERN.search("See @src/file.py for details") is not None
