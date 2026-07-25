"""Tests for the Bash tool's best-effort file-tracking heuristics.

These cover the argv parsing that used to live inside ``BashTool.call_with_args``, where it
could only be reached by actually spawning a subprocess.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from klaude_code.protocol.models import FileStatus
from klaude_code.tool.shell.file_tracking import (
    ShellFileTracker,
    hash_file_content_sha256,
    resolve_in_dir,
)


def _tracker(work_dir: Path) -> tuple[dict[str, FileStatus], ShellFileTracker]:
    entries: dict[str, FileStatus] = {}
    return entries, ShellFileTracker(entries, work_dir)


def _write(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestHashFileContentSha256:
    def test_text_file_is_hashed_line_by_line_as_utf8(self, tmp_path: Path) -> None:
        target = _write(tmp_path / "a.txt", "one\ntwo\n")

        expected = hashlib.sha256()
        expected.update(b"one\n")
        expected.update(b"two\n")

        assert hash_file_content_sha256(str(target)) == expected.hexdigest()

    def test_binary_suffix_is_hashed_as_raw_bytes(self, tmp_path: Path) -> None:
        # Bytes that are not valid UTF-8, so the text path would mangle them.
        payload = b"\x89PNG\r\n\x1a\n\xff\xfe"
        target = tmp_path / "img.png"
        target.write_bytes(payload)

        assert hash_file_content_sha256(str(target)) == hashlib.sha256(payload).hexdigest()

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert hash_file_content_sha256(str(tmp_path / "nope.txt")) is None

    def test_directory_returns_none(self, tmp_path: Path) -> None:
        assert hash_file_content_sha256(str(tmp_path)) is None


class TestResolveInDir:
    def test_relative_path_resolves_against_base_dir(self, tmp_path: Path) -> None:
        assert resolve_in_dir(str(tmp_path), "sub/a.txt") == str(tmp_path / "sub" / "a.txt")

    def test_absolute_path_ignores_base_dir(self, tmp_path: Path) -> None:
        absolute = str(tmp_path / "elsewhere.txt")
        assert resolve_in_dir("/some/other/dir", absolute) == absolute


class TestCat:
    def test_tracks_the_read_file(self, tmp_path: Path) -> None:
        target = _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("cat a.txt")

        assert str(target) in entries
        assert entries[str(target)].content_sha256 == hash_file_content_sha256(str(target))

    def test_tracks_multiple_files_and_skips_flags_and_stdin(self, tmp_path: Path) -> None:
        first = _write(tmp_path / "a.txt")
        second = _write(tmp_path / "b.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("cat -n a.txt - b.txt")

        assert set(entries) == {str(first), str(second)}

    def test_missing_file_is_not_tracked(self, tmp_path: Path) -> None:
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("cat nope.txt")

        assert entries == {}

    def test_directory_is_not_tracked(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("cat sub")

        assert entries == {}


class TestCdPrefix:
    def test_cd_then_cat_resolves_relative_to_that_dir(self, tmp_path: Path) -> None:
        target = _write(tmp_path / "sub" / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("cd sub && cat a.txt")

        assert str(target) in entries

    def test_chained_cd_accumulates(self, tmp_path: Path) -> None:
        target = _write(tmp_path / "sub" / "deep" / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("cd sub && cd deep && cat a.txt")

        assert str(target) in entries

    def test_cd_dash_does_not_change_base_dir(self, tmp_path: Path) -> None:
        target = _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("cd - && cat a.txt")

        assert str(target) in entries

    def test_cd_with_nothing_after_it_is_a_noop(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("cd sub && ")

        assert entries == {}


class TestSed:
    def test_in_place_edit_tracks_the_file(self, tmp_path: Path) -> None:
        target = _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("sed -i 's/old/new/' a.txt")

        assert str(target) in entries

    def test_print_script_tracks_the_file(self, tmp_path: Path) -> None:
        target = _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("sed -n '1p' a.txt")

        assert str(target) in entries

    def test_script_without_file_operand_tracks_nothing(self, tmp_path: Path) -> None:
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("sed 's/old/new/'")

        assert entries == {}


class TestMv:
    def test_entry_moves_to_the_new_path(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)
        entries[str(source)] = FileStatus(mtime=1.0, content_sha256="stale")

        # Perform the rename, then let the tracker observe it.
        moved = tmp_path / "b.txt"
        source.rename(moved)
        tracker.update_from_command("mv a.txt b.txt")

        assert str(source) not in entries
        assert str(moved) in entries
        assert entries[str(moved)].content_sha256 == hash_file_content_sha256(str(moved))

    def test_move_into_directory_keys_on_basename(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "a.txt")
        dest_dir = tmp_path / "sub"
        dest_dir.mkdir()
        entries, tracker = _tracker(tmp_path)

        source.rename(dest_dir / "a.txt")
        tracker.update_from_command("mv a.txt sub")

        assert str(dest_dir / "a.txt") in entries

    def test_classification_flags_carry_over(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "AGENTS.md")
        entries, tracker = _tracker(tmp_path)
        entries[str(source)] = FileStatus(mtime=1.0, is_memory=True, is_skill=True)

        moved = tmp_path / "AGENTS-renamed.md"
        source.rename(moved)
        tracker.update_from_command("mv AGENTS.md AGENTS-renamed.md")

        assert entries[str(moved)].is_memory is True
        assert entries[str(moved)].is_skill is True

    def test_flags_and_double_dash_are_skipped(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        moved = tmp_path / "b.txt"
        source.rename(moved)
        tracker.update_from_command("mv -f -- a.txt b.txt")

        assert str(moved) in entries

    def test_single_operand_is_a_noop(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("mv a.txt")

        assert entries == {}

    def test_stale_source_entry_is_dropped_even_when_dest_is_missing(self, tmp_path: Path) -> None:
        source = tmp_path / "a.txt"
        entries, tracker = _tracker(tmp_path)
        entries[str(source)] = FileStatus(mtime=1.0, content_sha256="stale")

        # Destination never appears (e.g. the mv actually failed).
        tracker.update_from_command("mv a.txt b.txt")

        assert str(source) not in entries
        assert str(tmp_path / "b.txt") not in entries


class TestUnrecognizedInput:
    def test_unbalanced_quotes_are_ignored(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        # shlex.split raises ValueError here; the tracker must not propagate it.
        tracker.update_from_command("cat 'a.txt")

        assert entries == {}

    def test_empty_command_is_ignored(self, tmp_path: Path) -> None:
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("")

        assert entries == {}

    def test_unknown_command_tracks_nothing(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.txt")
        entries, tracker = _tracker(tmp_path)

        tracker.update_from_command("wc -l a.txt")

        assert entries == {}
