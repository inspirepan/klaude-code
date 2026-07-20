import asyncio
from types import SimpleNamespace
from typing import Any

from prompt_toolkit.completion import Completion
from prompt_toolkit.document import Document
from rich.text import Text

from klaude_code.tui.commands import DynamicSeparatorText, PromptStatusLine, SpinnerStatusLine
from klaude_code.tui.components.user_input import USER_MESSAGE_MARK
from klaude_code.tui.input.key_bindings import merge_dequeued_messages, split_queued_message_edit_text
from klaude_code.tui.input.paste import expand_paste_markers, store_paste
from klaude_code.tui.input.prompt_status_bar import PromptBottomBar
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput, _PasteAwareFileHistory
from klaude_code.tui.renderer import TUICommandRenderer


def _build_input(text: str, *, invalidations: SimpleNamespace | None = None) -> PromptToolkitInput:
    prompt_input: Any = object.__new__(PromptToolkitInput)
    invalidations = invalidations or SimpleNamespace(count=0)

    def invalidate() -> None:
        invalidations.count += 1

    document = Document(text=text, cursor_position=len(text))

    prompt_input._prompt_text = USER_MESSAGE_MARK
    prompt_input._session = SimpleNamespace(
        default_buffer=SimpleNamespace(text=text, document=document, complete_state=None),
        app=SimpleNamespace(invalidate=invalidate),
    )
    prompt_input._clipboard_has_image = False
    prompt_input._refresh_status = None
    prompt_input._request_interrupt = None
    prompt_input._get_current_model_config_name = lambda: "test-model"
    prompt_input._next_prefill_text = None
    prompt_input._prompt_suggestion = None
    prompt_input._last_completion_panel_completions = ()
    prompt_input._last_completion_panel_selected_index = None
    prompt_input._last_completion_panel_context_key = None
    prompt_input._completion_panel_snapshot_cache = None
    prompt_input._bottom_bar = PromptBottomBar(invalidate=invalidate)
    prompt_input._queued_edit_active = False
    prompt_input._agent_running = False
    prompt_input._prompt_active = False
    prompt_input._prompt_pause_waiter = None
    prompt_input._external_input_pause_count = 0
    prompt_input._external_input_resume_event = asyncio.Event()
    prompt_input._external_input_resume_event.set()
    prompt_input._model_picker = None
    return prompt_input  # type: ignore[return-value]


def _status(text: str) -> PromptStatusLine:
    return PromptStatusLine(text, "status")


def _metadata(text: str) -> PromptStatusLine:
    return PromptStatusLine(text, "metadata")


def test_set_next_prefill_stores_text() -> None:
    prompt_input: Any = _build_input("hello")
    prompt_input._next_prefill_text = None

    prompt_input.set_next_prefill("retry me")

    assert prompt_input._next_prefill_text == "retry me"


def test_next_prefill_waits_until_idle_prompt() -> None:
    prompt_input: Any = _build_input("")
    prompt_input._agent_running = True
    prompt_input.set_next_prefill("retry me")

    assert prompt_input._take_next_prefill_text() is None
    assert prompt_input._next_prefill_text == "retry me"

    prompt_input._agent_running = False

    assert prompt_input._take_next_prefill_text() == "retry me"
    assert prompt_input._next_prefill_text is None


def test_placeholder_shows_paste_image_hint_with_prompt_suggestion() -> None:
    prompt_input = _build_input("")
    prompt_input._prompt_suggestion = "run tests"
    prompt_input._clipboard_has_image = True

    placeholder = prompt_input._build_placeholder()

    assert ("class:prompt-suggestion", "run tests") in placeholder
    assert any("ctrl+v to paste image" in text and "\n" not in text for _style, text, *_ in placeholder)


def test_running_placeholder_prompts_for_follow_up() -> None:
    prompt_input = _build_input("")
    prompt_input._agent_running = True
    prompt_input._prompt_suggestion = "run tests"

    placeholder = prompt_input._build_placeholder()

    assert placeholder == [("class:placeholder", "   Queue a follow-up")]


def test_running_prompt_uses_cyan_style() -> None:
    prompt_input = _build_input("")

    assert prompt_input._get_prompt_message() == [("class:prompt", USER_MESSAGE_MARK)]

    prompt_input._agent_running = True

    assert prompt_input._get_prompt_message() == [("class:prompt.running", USER_MESSAGE_MARK)]


def test_status_lines_render_above_prompt() -> None:
    prompt_input = _build_input("")

    prompt_input.set_status_lines(
        (_status("Loading..."), _metadata("in 10")), separator_text="1m51s · esc to interrupt"
    )
    bar = prompt_input._bottom_bar

    assert bar._status_lines == (_status("Loading..."), _metadata("in 10"))
    assert bar._running_separator_label == "1m51s · esc to interrupt"
    assert bar._get_status_fragments() == [
        ("class:meta", "·   "),
        ("class:meta", "Loading..."),
    ]
    assert bar.metadata_footer_lines == ("in 10",)


def test_startup_loading_survives_agent_status_clear_without_marking_agent_running() -> None:
    async def _scenario() -> None:
        prompt_input = _build_input("")
        bar = prompt_input._bottom_bar

        prompt_input.set_startup_loading(True)

        assert prompt_input._is_agent_running() is False
        assert prompt_input._build_placeholder() == []
        assert bar._get_status_fragments() == [
            ("class:meta", "·   "),
            ("class:meta", "Preparing session…"),
        ]

        prompt_input.set_status_lines((_status("Replaying…"),))
        prompt_input.set_status_lines(())

        assert bar._get_status_fragments() == [
            ("class:meta", "·   "),
            ("class:meta", "Preparing session…"),
        ]

        prompt_input.set_startup_loading(False)

        assert bar._get_status_fragments() == []
        bar.stop()

    asyncio.run(_scenario())


def test_status_window_height_stays_stable_until_status_clears() -> None:
    prompt_input = _build_input("")

    assert prompt_input._bottom_bar._status_window_height() == 1

    prompt_input.set_status_lines(
        (_status("Loading..."), _metadata("in 10")), separator_text="1m51s · esc to interrupt"
    )
    prompt_input.set_status_lines((_status("Loading..."),))

    assert prompt_input._bottom_bar._status_window_height() == 1

    prompt_input.set_status_lines(())

    assert prompt_input._bottom_bar._status_window_height() == 1


def test_status_clear_defers_height_collapse_under_loop() -> None:
    async def _scenario() -> None:
        invalidations = SimpleNamespace(count=0)
        prompt_input = _build_input("", invalidations=invalidations)
        bar = prompt_input._bottom_bar

        prompt_input.set_status_lines((_status("Typing…"),), separator_text="13s · esc to interrupt")
        assert bar._status_reserved_line_count == 1

        prompt_input.set_status_lines((), separator_text=None)
        assert bar._status_lines == ()
        assert bar._get_status_fragments() == []
        assert bar._status_reserved_line_count == 1
        assert bar._status_collapse_handle is not None

        prompt_input.set_status_lines((_status("Loading…"),), separator_text="14s · esc to interrupt")
        assert bar._status_collapse_handle is None
        assert bar._status_reserved_line_count == 1

    asyncio.run(_scenario())


def test_metadata_footer_survives_status_only_and_clear_updates() -> None:
    prompt_input = _build_input("")
    bar = prompt_input._bottom_bar

    prompt_input.set_status_lines((_status("Typing…"), _metadata("in 10 · out 2")))
    prompt_input.set_status_lines((_status("Typing…"),))

    assert bar.metadata_footer_lines == ("in 10 · out 2",)

    prompt_input.set_status_lines(())

    assert bar.metadata_footer_lines == ("in 10 · out 2",)


def test_running_separator_follows_status_sink_snapshot() -> None:
    prompt_input = _build_input("")

    prompt_input.set_status_lines((_status("Loading..."),), separator_text="1m51s · esc to interrupt")
    prompt_input.set_status_lines((), separator_text="1m52s · esc to interrupt")

    assert prompt_input._bottom_bar._running_separator_label == "1m52s · esc to interrupt"


def test_bottom_line_updates_skip_unchanged_invalidations() -> None:
    invalidations = SimpleNamespace(count=0)
    prompt_input = _build_input("", invalidations=invalidations)

    prompt_input.set_stream_lines(("tail",))
    prompt_input.set_stream_lines(("tail",))
    prompt_input.set_status_lines((_status("Loading..."),))
    prompt_input.set_status_lines((_status("Loading..."),))
    prompt_input.set_pending_messages(("queued",))
    prompt_input.set_pending_messages(("queued",))

    assert invalidations.count == 3


def test_running_separator_uses_prompt_width_fallback() -> None:
    prompt_input = _build_input("")

    assert prompt_input._bottom_bar._get_running_separator_fragments() == [("class:lines", "─" * 80)]


def test_running_separator_stays_plain_when_interrupt_hint_is_present() -> None:
    prompt_input = _build_input("")
    prompt_input._bottom_bar._running_separator_label = "1m51s · esc to interrupt"

    assert prompt_input._bottom_bar._get_running_separator_fragments() == [("class:lines", "─" * 80)]


def test_input_footer_renders_interrupt_hint_after_context() -> None:
    prompt_input: Any = _build_input("")
    prompt_input._bottom_bar._running_separator_label = "1m51s · esc to interrupt"

    assert prompt_input._get_input_footer_height() == 2
    assert prompt_input._get_input_footer_fragments()[-2:] == [
        ("class:meta", " · "),
        ("class:meta", "1m51s · esc to interrupt"),
    ]


def test_input_footer_context_name_uses_blue_not_placeholder() -> None:
    prompt_input: Any = _build_input("")

    fragments = prompt_input._build_prompt_context_fragments(prefix="  ")

    assert fragments[0] == ("class:placeholder", "  ")
    assert fragments[1][0] == "class:accent.blue"


def test_input_footer_reserves_idle_metadata_row() -> None:
    prompt_input: Any = _build_input("")

    assert prompt_input._get_input_footer_height() == 2
    assert "\n" not in [text for _style, text, *_ in prompt_input._get_input_footer_fragments()]


def test_input_footer_stays_hidden_while_completion_is_loading() -> None:
    prompt_input: Any = _build_input("@use")
    buffer: Any = prompt_input._session.default_buffer
    buffer.complete_state = SimpleNamespace(completions=[])  # ty: ignore[invalid-assignment]

    assert prompt_input._get_input_footer_height() == 1
    assert prompt_input._get_input_footer_fragments() == []


def test_input_footer_stays_visible_for_non_completion_text_loading_state() -> None:
    prompt_input: Any = _build_input("hello")
    buffer: Any = prompt_input._session.default_buffer
    buffer.complete_state = SimpleNamespace(completions=[])  # ty: ignore[invalid-assignment]

    rendered = "".join(text for _style, text, *_ in prompt_input._get_input_footer_fragments())

    assert prompt_input._get_input_footer_height() == 2
    assert "test-model" in rendered


def test_completion_panel_uses_cached_items_while_next_results_are_loading() -> None:
    prompt_input: Any = _build_input("@useAg")
    prompt_input._last_completion_panel_completions = (
        Completion(text="@src/hooks/useApiKey.ts ", display="src/hooks/useApiKey.ts"),
        Completion(text="@src/agent/useAgentSkills.ts ", display="src/agent/useAgentSkills.ts"),
    )
    prompt_input._last_completion_panel_context_key = "at"
    buffer: Any = prompt_input._session.default_buffer
    buffer.complete_state = SimpleNamespace(completions=[], complete_index=None)  # ty: ignore[invalid-assignment]

    rendered = "".join(text for _style, text, *_ in prompt_input._get_completion_panel_fragments())

    assert prompt_input._get_completion_panel_height() == 1
    assert "src/agent/useAgentSkills.ts" in rendered
    assert "src/hooks/useApiKey.ts" not in rendered


def test_completion_panel_does_not_reuse_cache_across_completion_contexts() -> None:
    prompt_input: Any = _build_input("/use")
    prompt_input._last_completion_panel_completions = (
        Completion(text="@src/agent/useAgentSkills.ts ", display="src/agent/useAgentSkills.ts"),
    )
    prompt_input._last_completion_panel_context_key = "at"
    buffer: Any = prompt_input._session.default_buffer
    buffer.complete_state = SimpleNamespace(completions=[], complete_index=None)  # ty: ignore[invalid-assignment]

    assert prompt_input._get_completion_panel_height() == 0
    assert prompt_input._get_completion_panel_fragments() == []


def test_input_height_estimate_counts_soft_wrapped_lines() -> None:
    prompt_input = _build_input("x" * 20)
    prompt_input._prompt_text = "❯ "

    assert prompt_input._estimate_input_visual_rows(columns=8) == 4


def test_input_height_estimate_counts_newlines_and_soft_wraps() -> None:
    prompt_input = _build_input("short\n" + "x" * 13)
    prompt_input._prompt_text = "❯ "

    assert prompt_input._estimate_input_visual_rows(columns=8) == 4


def test_input_window_max_height_accounts_for_bottom_layout() -> None:
    prompt_input = _build_input("\n".join(str(i) for i in range(50)))
    prompt_input.set_stream_lines(("live 1", "live 2", "live 3"))
    prompt_input.set_status_lines((_status("Loading…"), _metadata("in 12 · cache 3k")))
    prompt_input.set_pending_messages(("first queued", "second queued"))

    assert prompt_input._get_max_input_window_rows(24) == 10


def test_input_window_max_height_keeps_minimum_row_on_tiny_terminal() -> None:
    prompt_input = _build_input("\n".join(str(i) for i in range(50)))
    prompt_input.set_stream_lines(("live 1", "live 2", "live 3"))
    prompt_input.set_status_lines((_status("Loading…"), _metadata("in 12 · cache 3k")))
    prompt_input.set_pending_messages(("first queued", "second queued"))

    assert prompt_input._get_max_input_window_rows(8) == 1


def test_input_footer_renders_metadata_below_context_line() -> None:
    prompt_input: Any = _build_input("")
    prompt_input.set_status_lines(
        (_status("Loading…"), _metadata("in 15.3k · cache 28.2k")),
        separator_text="11s · esc to interrupt",
    )

    assert prompt_input._get_input_footer_height() == 2
    assert prompt_input._get_input_footer_fragments()[-4:] == [
        ("class:meta", " · "),
        ("class:meta", "11s · esc to interrupt"),
        ("", "\n"),
        ("class:metadata.footer", "  in 15.3k · cache 28.2k"),
    ]


def test_renderer_status_sink_separates_interrupt_hint() -> None:
    updates: list[tuple[tuple[PromptStatusLine, ...], str | None]] = []
    renderer = TUICommandRenderer(status_sink=lambda lines, separator_text: updates.append((lines, separator_text)))
    elapsed = SimpleNamespace(text="1m51s")

    renderer.set_progress_ui_suspended(True)
    renderer.spinner_start()
    renderer.spinner_update(
        Text("in 12 · cache 3k"),
        (SpinnerStatusLine(text=Text("Loading…")),),
        separator_text=DynamicSeparatorText(lambda: f"{elapsed.text} · esc to interrupt"),
    )

    lines, separator_text = updates[-1]
    assert lines == (_status("Loading…"), _metadata("in 12 · cache 3k"))
    assert all("esc to interrupt" not in line.text for line in lines)
    assert separator_text == "1m51s · esc to interrupt"

    elapsed.text = "1m52s"
    renderer.refresh_prompt_status()
    assert updates[-1][1] == "1m52s · esc to interrupt"


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

    bar = prompt_input._bottom_bar
    assert bar._stream_lines == ("  line one", "  line two")
    assert bar._get_stream_fragments() == [
        ("class:meta", "  line one"),
        ("", "\n"),
        ("class:meta", "  line two"),
    ]


def test_stream_lines_height_high_water_holds_during_session() -> None:
    """Stream height must not shrink mid-stream — that's the source of flicker."""
    invalidations = SimpleNamespace(count=0)
    prompt_input = _build_input("", invalidations=invalidations)
    bar = prompt_input._bottom_bar

    prompt_input.set_stream_lines(("a", "b", "c"))
    assert bar._stream_reserved_line_count == 3
    base_invalidations = invalidations.count

    # Frame-to-frame shrink: content drops to one line but reservation must hold.
    prompt_input.set_stream_lines(("x",))
    assert bar._stream_reserved_line_count == 3
    assert bar._stream_lines == ("x",)

    # Transient empty content (e.g. MarkdownStream consuming all live into stable)
    # does not collapse the area — reserved height stays.
    prompt_input.set_stream_lines(())
    assert bar._stream_reserved_line_count == 3
    assert bar._stream_lines == ()

    # Subsequent grow above the high-water raises it.
    prompt_input.set_stream_lines(("a", "b", "c", "d", "e"))
    assert bar._stream_reserved_line_count == 5

    # Each of the four state changes above invalidated once.
    assert invalidations.count - base_invalidations == 3


def test_stream_lines_end_of_stream_collapses_reserved() -> None:
    prompt_input = _build_input("")
    bar = prompt_input._bottom_bar

    prompt_input.set_stream_lines(("a", "b", "c"))
    assert bar._stream_reserved_line_count == 3

    # No running loop in this synchronous test path → fallback collapses
    # immediately so non-interactive callers keep deterministic behavior.
    prompt_input.set_stream_lines((), end_of_stream=True)
    assert bar._stream_reserved_line_count == 0
    assert bar._stream_lines == ()


def test_stream_lines_end_of_stream_defers_height_collapse_under_loop() -> None:
    """Under a running asyncio loop, end_of_stream clears visible content
    but holds the reserved height for a brief debounce window. This stops
    prompt-toolkit from briefly painting the input field right under the
    last assistant message before the adjacent task-end events render to
    scrollback."""
    import asyncio

    async def _scenario() -> None:
        prompt_input = _build_input("")
        bar = prompt_input._bottom_bar

        prompt_input.set_stream_lines(("a", "b", "c"))
        assert bar._stream_reserved_line_count == 3

        prompt_input.set_stream_lines((), end_of_stream=True)
        # Lines cleared immediately…
        assert bar._stream_lines == ()
        # …but reserved height is held pending the debounce timer.
        assert bar._stream_reserved_line_count == 3
        assert bar._stream_collapse_handle is not None

        # A new chunk before the timer fires cancels the collapse.
        prompt_input.set_stream_lines(("d",))
        assert bar._stream_collapse_handle is None
        assert bar._stream_reserved_line_count == 3
        assert bar._stream_lines == ("d",)

    asyncio.run(_scenario())


def test_status_spinner_prefixes_each_status_line_but_not_metadata() -> None:
    prompt_input = _build_input("")
    prompt_input._bottom_bar._status_spinner_frame = 1

    prompt_input.set_status_lines(
        (
            _status("Finding: session"),
            _status("Thinking…"),
            _metadata("in 12 · cache 3k"),
            _metadata("↑104.8k ◎390.1k ↓5.5k ∵404 · 77.7k/272k (28.6%) · $0.8975"),
        ),
        separator_text="0s · esc to interrupt",
    )

    bar = prompt_input._bottom_bar
    assert bar._get_status_fragments() == [
        ("class:meta", "··  "),
        ("class:meta", "Finding: session"),
        ("", "\n"),
        ("class:meta", "··  "),
        ("class:meta", "Thinking…"),
    ]
    assert bar.metadata_footer_lines == (
        "in 12 · cache 3k",
        "↑104.8k ◎390.1k ↓5.5k ∵404 · 77.7k/272k (28.6%) · $0.8975",
    )
    assert bar._running_separator_label == "0s · esc to interrupt"


def test_status_spinner_does_not_prefix_wrapped_token_metadata() -> None:
    prompt_input = _build_input("")
    prompt_input._bottom_bar._status_spinner_frame = 4

    prompt_input.set_status_lines(
        (
            _status("Loading…"),
            _metadata("in 18.2k · cache 33.8k · out 1.1k · thought 89 · 26.7k/272k (9.8%) · cost $0.1430 · 7"),
        )
    )

    assert prompt_input._bottom_bar._get_status_fragments() == [
        ("class:meta", "  · "),
        ("class:meta", "Loading…"),
    ]
    assert prompt_input._bottom_bar.metadata_footer_lines == (
        "in 18.2k · cache 33.8k · out 1.1k · thought 89 · 26.7k/272k (9.8%) · cost $0.1430 · 7",
    )


def test_status_metadata_kind_controls_spinner_prefix() -> None:
    prompt_input = _build_input("")
    prompt_input._bottom_bar._status_spinner_frame = 2

    prompt_input.set_status_lines((_status("Loading…"), _metadata("not token-shaped metadata")))

    assert prompt_input._bottom_bar._get_status_fragments() == [
        ("class:meta", "··· "),
        ("class:meta", "Loading…"),
    ]
    assert prompt_input._bottom_bar.metadata_footer_lines == ("not token-shaped metadata",)


def test_pending_messages_render_above_prompt() -> None:
    prompt_input = _build_input("")

    prompt_input.set_pending_messages(("first queued", "second\nqueued"))

    bar = prompt_input._bottom_bar
    assert bar._pending_messages == ("first queued", "second\nqueued")
    assert bar._get_pending_message_fragments() == [
        ("class:meta", "Queued follow-up message (2 pending) · ↑ to edit."),
        ("", "\n"),
        ("class:meta", "  1. "),
        ("class:user.input", "first queued"),
        ("", "\n"),
        ("class:meta", "  2. "),
        ("class:user.input", "second queued"),
    ]


def test_merge_dequeued_messages_keeps_queue_before_current_editor_text() -> None:
    assert merge_dequeued_messages(("first", "second"), "current") == (
        "first\n--- split ---\nsecond\n--- split ---\ncurrent"
    )
    assert merge_dequeued_messages(("first", ""), "") == "first"


def test_split_queued_message_edit_text_uses_separator_lines() -> None:
    assert split_queued_message_edit_text("first\n---\nsecond edited") == ("first", "second edited")
    assert split_queued_message_edit_text("first\n --- split --- \nsecond edited") == ("first", "second edited")
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
