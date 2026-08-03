from __future__ import annotations

from klaude_code.cli.headless_cmd import (
    EXIT_FAILED,
    EXIT_WAITING_INPUT,
    _exit_code_for_states,  # pyright: ignore[reportPrivateUsage]
    _pending_request_lines,  # pyright: ignore[reportPrivateUsage]
    _short_id,  # pyright: ignore[reportPrivateUsage]
    _shorten,  # pyright: ignore[reportPrivateUsage]
    _split_targets,  # pyright: ignore[reportPrivateUsage]
)


def test_split_targets_mixes_spaces_and_commas() -> None:
    assert _split_targets(["a3f2,9b01", "fix-tests"]) == ["a3f2", "9b01", "fix-tests"]
    assert _split_targets(["a, b ,", ""]) == ["a", "b"]


def test_exit_code_severity_order() -> None:
    assert _exit_code_for_states(["idle", "idle"]) == 0
    assert _exit_code_for_states(["idle", "waiting_input"]) == EXIT_WAITING_INPUT
    assert _exit_code_for_states(["waiting_input", "failed"]) == EXIT_FAILED


def test_shorten_and_short_id() -> None:
    assert _shorten("word " * 40, 20).endswith("…")
    assert len(_shorten("word " * 40, 20)) == 20
    assert _short_id("abcdef1234567890") == "abcdef12"


def test_pending_request_lines_with_options() -> None:
    lines = _pending_request_lines(
        {
            "type": "question",
            "prompt": "Which option?",
            "options": [
                {"index": 1, "label": "A", "description": "choose A"},
                {"index": 2, "label": "B", "description": ""},
            ],
        },
        target="a3f2c1",
    )
    assert lines[0] == "pending question: Which option?"
    assert lines[1] == "  1. A — choose A"
    assert lines[2] == "  2. B"
    assert lines[3] == "answer with: klaude respond a3f2c1 --option N"


def test_pending_request_lines_free_text() -> None:
    lines = _pending_request_lines({"type": "question", "prompt": "Say what?", "options": []}, target="a3f2c1")
    assert lines[-1] == "answer with: klaude respond a3f2c1 --text '...'"
