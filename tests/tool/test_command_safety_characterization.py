"""Characterization tests for command_safety (G6).

Locks in the CURRENT verdicts of
``klaude_code.tool.shell.command_safety.is_safe_command`` so a later refactor
stays behavior-preserving. Asserts what the code currently DOES.

``tests/tool/test_command_safety.py`` owns the rm/trash allow/deny matrix;
these tests add only the boundary behaviors that are easy to break in a
refactor:
- unparseable commands (unbalanced quotes) treated as SAFE (@164)
- shell operators are NOT split, so only argv[0] decides the verdict
- empty / whitespace-only commands are UNSAFE ("Empty command")
- only the bare ``rm`` / ``trash`` tokens are matched (case-sensitive, no path)

Representative rm/trash verdicts for the unrestricted-command default live in
that owner file, not here.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

from klaude_code.tool import is_safe_command


@pytest.fixture
def work_dir() -> Iterator[str]:
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "file.txt"), "w", encoding="utf-8") as f:
            f.write("hello\n")
        yield d


# --------------------------------------------------------------------------
# Unparseable commands -> SAFE (let the real shell surface syntax errors)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'echo "unterminated',
        "echo 'unterminated",
        "rm 'unterminated",  # even an rm with unbalanced quote parses to ValueError first
        'trash "oops',
    ],
)
def test_unparseable_command_is_safe(command: str, work_dir: str) -> None:
    result = is_safe_command(command, work_dir=work_dir)
    assert result.is_safe is True
    assert result.error_msg == ""


# --------------------------------------------------------------------------
# Operators are NOT split: only argv[0] is inspected
# --------------------------------------------------------------------------


def test_operators_not_split_first_token_decides(work_dir: str) -> None:
    # 'ls && rm /etc/passwd' parses to argv[0] == 'ls', so it is treated as safe
    # even though a dangerous rm follows.
    result = is_safe_command("ls && rm /etc/passwd", work_dir=work_dir)
    assert result.is_safe is True


def test_pipeline_first_token_decides(work_dir: str) -> None:
    result = is_safe_command("rg hello file.txt | wc -l", work_dir=work_dir)
    assert result.is_safe is True


def test_rm_as_first_token_in_pipeline_is_still_checked(work_dir: str) -> None:
    # Here argv[0] == 'rm' and the operands include the pipe / second command
    # tokens; the absolute path /etc/passwd is rejected.
    result = is_safe_command("rm /etc/passwd | cat", work_dir=work_dir)
    assert result.is_safe is False
    assert "absolute path" in result.error_msg.lower()


# --------------------------------------------------------------------------
# Empty / whitespace-only -> UNSAFE
# --------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["", "   ", "\t"])
def test_empty_command_is_unsafe(command: str, work_dir: str) -> None:
    result = is_safe_command(command, work_dir=work_dir)
    assert result.is_safe is False
    assert result.error_msg == "Empty command"


# --------------------------------------------------------------------------
# Matching is on the bare token only (case-sensitive, no path/alias)
# --------------------------------------------------------------------------


def test_rm_matching_is_case_sensitive(work_dir: str) -> None:
    # 'RM' is not 'rm', so the dangerous-path rules do not apply.
    result = is_safe_command("RM /etc/passwd", work_dir=work_dir)
    assert result.is_safe is True


def test_rm_with_path_prefix_not_matched(work_dir: str) -> None:
    # '/bin/rm' != 'rm', so it falls through to the default-allow branch.
    result = is_safe_command("/bin/rm /etc/passwd", work_dir=work_dir)
    assert result.is_safe is True
