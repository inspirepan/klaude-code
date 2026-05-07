import asyncio
from types import SimpleNamespace
from typing import Any

from klaude_code.tui.components.user_input import USER_MESSAGE_MARK
from klaude_code.tui.input.key_bindings import merge_dequeued_messages, split_queued_message_edit_text
from klaude_code.tui.input.paste import expand_paste_markers, store_paste
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput, _PasteAwareFileHistory


def _build_input(text: str, *, invalidations: SimpleNamespace | None = None) -> PromptToolkitInput:
    prompt_input: Any = object.__new__(PromptToolkitInput)
    invalidations = invalidations or SimpleNamespace(count=0)

    def invalidate() -> None:
        invalidations.count += 1

    prompt_input._prompt_text = USER_MESSAGE_MARK
    prompt_input._session = SimpleNamespace(default_buffer=SimpleNamespace(text=text), app=SimpleNamespace(invalidate=invalidate))
    prompt_input._clipboard_has_image = False
    prompt_input._status_spinner_task = None
    prompt_input._status_spinner_frame = 0
    prompt_input._refresh_status = None
    prompt_input._request_interrupt = None
    prompt_input._prompt_suggestion = None
    prompt_input._stream_lines = ()
    prompt_input._status_lines = ()
    prompt_input._status_reserved_line_count = 0
    prompt_input._pending_messages = ()
    prompt_input._queued_edit_active = False
    prompt_input._prompt_active = False
    prompt_input._prompt_pause_waiter = None
    prompt_input._external_input_pause_count = 0
    prompt_input._external_input_resume_event = asyncio.Event()
    prompt_input._external_input_resume_event.set()
    return prompt_input  # type: ignore[return-value]


def test_set_next_prefill_stores_text() -> None:
    prompt_input: Any = _build_input("hello")
    prompt_input._next_prefill_text = None

    prompt_input.set_next_prefill("retry me")

    assert prompt_input._next_prefill_text == "retry me"


def test_placeholder_shows_paste_image_hint_with_prompt_suggestion() -> None:
    prompt_input = _build_input("")
    prompt_input._prompt_suggestion = "run tests"
    prompt_input._clipboard_has_image = True

    placeholder = prompt_input._build_placeholder()

    assert ("class:prompt-suggestion", "run tests") in placeholder
    assert any("ctrl+v to paste image" in text and "\n" not in text for _style, text, *_ in placeholder)


def test_running_placeholder_prompts_for_follow_up() -> None:
    prompt_input = _build_input("")
    prompt_input._request_interrupt = lambda: None
    prompt_input._prompt_suggestion = "run tests"

    placeholder = prompt_input._build_placeholder()

    assert placeholder == [("class:placeholder", "   Queue a follow-up")]


def test_running_prompt_uses_cyan_style() -> None:
    prompt_input = _build_input("")

    assert prompt_input._get_prompt_message() == [("class:prompt", USER_MESSAGE_MARK)]

    prompt_input._request_interrupt = lambda: None

    assert prompt_input._get_prompt_message() == [("class:prompt.running", USER_MESSAGE_MARK)]


def test_status_lines_render_above_prompt() -> None:
    prompt_input = _build_input("")

    prompt_input.set_status_lines(("Loading...", "in 10 · esc to interrupt"))

    assert prompt_input._status_lines == ("Loading...", "in 10 · esc to interrupt")
    assert prompt_input._get_status_fragments() == [
        ("class:meta", "⠋ "),
        ("class:meta", "Loading..."),
        ("", "\n"),
        ("class:meta", "in 10 · esc to interrupt"),
    ]


def test_status_window_height_stays_stable_until_status_clears() -> None:
    prompt_input = _build_input("")

    prompt_input.set_status_lines(("Loading...", "in 10 · esc to interrupt"))
    prompt_input.set_status_lines(("Loading...",))

    assert prompt_input._status_window_height() == 2

    prompt_input.set_status_lines(())

    assert prompt_input._status_window_height() == 0


def test_bottom_line_updates_skip_unchanged_invalidations() -> None:
    invalidations = SimpleNamespace(count=0)
    prompt_input = _build_input("", invalidations=invalidations)

    prompt_input.set_stream_lines(("tail",))
    prompt_input.set_stream_lines(("tail",))
    prompt_input.set_status_lines(("Loading...",))
    prompt_input.set_status_lines(("Loading...",))
    prompt_input.set_pending_messages(("queued",))
    prompt_input.set_pending_messages(("queued",))

    assert invalidations.count == 3


def test_running_separator_uses_prompt_width_fallback() -> None:
    prompt_input = _build_input("")

    assert prompt_input._get_running_separator_fragments() == [("class:meta", "╸" * 80)]


def test_interrupt_handler_invalidates_running_separator() -> None:
    invalidations = SimpleNamespace(count=0)
    prompt_input: Any = _build_input("", invalidations=invalidations)

    prompt_input.set_interrupt_handler(lambda: None)
    prompt_input.set_interrupt_handler(prompt_input._request_interrupt)
    prompt_input.set_interrupt_handler(None)

    assert invalidations.count == 2


def test_stream_lines_render_above_status() -> None:
    prompt_input = _build_input("")

    prompt_input.set_stream_lines(("  line one", "  line two"))

    assert prompt_input._stream_lines == ("  line one", "  line two")
    assert prompt_input._get_stream_fragments() == [
        ("class:meta", "  line one"),
        ("", "\n"),
        ("class:meta", "  line two"),
    ]


def test_status_spinner_prefixes_each_status_line_but_not_metadata() -> None:
    prompt_input = _build_input("")
    prompt_input._status_spinner_frame = 1

    prompt_input.set_status_lines(
        (
            "Finding: session",
            "Thinking…",
            "in 12 · cache 3k",
            "0s · esc to interrupt",
            "↑104.8k ◎390.1k ↓5.5k ∵404 · 77.7k/272k (28.6%) · $0.8975 · 0s · esc to interrupt",
        )
    )

    assert prompt_input._get_status_fragments() == [
        ("class:meta", "⠙ "),
        ("class:meta", "Finding: session"),
        ("", "\n"),
        ("class:meta", "⠙ "),
        ("class:meta", "Thinking…"),
        ("", "\n"),
        ("class:meta", "in 12 · cache 3k"),
        ("", "\n"),
        ("class:meta", "0s · esc to interrupt"),
        ("", "\n"),
        ("class:meta", "↑104.8k ◎390.1k ↓5.5k ∵404 · 77.7k/272k (28.6%) · $0.8975 · 0s · esc to interrupt"),
    ]


def test_pending_messages_render_above_prompt() -> None:
    prompt_input = _build_input("")

    prompt_input.set_pending_messages(("first queued", "second\nqueued"))

    assert prompt_input._pending_messages == ("first queued", "second\nqueued")
    assert prompt_input._get_pending_message_fragments() == [
        ("class:meta", "Queued follow-up message (2 pending) · ↑ to edit."),
        ("", "\n"),
        ("class:meta", "  1. first queued"),
        ("", "\n"),
        ("class:meta", "  2. second queued"),
    ]


def test_merge_dequeued_messages_keeps_queue_before_current_editor_text() -> None:
    assert merge_dequeued_messages(("first", "second"), "current") == "first\n---\nsecond\n---\ncurrent"
    assert merge_dequeued_messages(("first", ""), "") == "first"


def test_split_queued_message_edit_text_uses_separator_lines() -> None:
    assert split_queued_message_edit_text("first\n---\nsecond edited") == ("first", "second edited")
    assert split_queued_message_edit_text("ordinary --- text") == ("ordinary --- text",)


def test_external_input_pause_waits_until_resume() -> None:
    async def _run() -> None:
        prompt_input = _build_input("")

        resume = await prompt_input.pause_for_external_input()

        assert prompt_input._external_input_pause_count == 1
        assert not prompt_input._external_input_resume_event.is_set()

        resume()

        assert prompt_input._external_input_pause_count == 0
        assert prompt_input._external_input_resume_event.is_set()

    asyncio.run(_run())


def test_paste_aware_history_stores_expanded_paste(tmp_path) -> None:
    paste_text = "alpha\nbeta"
    marker = store_paste(paste_text)
    expected = f"prefix \n{paste_text}\n suffix"
    history_path = tmp_path / "input_history.txt"

    history = _PasteAwareFileHistory(str(history_path))
    history.append_string(f"prefix {marker} suffix")

    assert history.get_strings() == [expected]
    assert list(_PasteAwareFileHistory(str(history_path)).load_history_strings()) == [expected]
    assert marker not in history_path.read_text(encoding="utf-8")
    assert expand_paste_markers(marker) == f"\n{paste_text}\n"
