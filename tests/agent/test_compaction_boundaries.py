import unittest
from pathlib import Path

from klaude_code.agent.compaction import compaction
from klaude_code.protocol import message
from klaude_code.session.session import Session


class TestCompactionBoundaries(unittest.TestCase):
    def test_find_cut_index_never_returns_tool_result(self) -> None:
        history: list[message.HistoryEvent] = [
            message.UserMessage(parts=[message.TextPart(text="hi")]),
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(call_id="call_1", tool_name="bash", arguments_json="{}"),
                ]
            ),
            message.ToolResultMessage(
                call_id="call_1",
                tool_name="bash",
                status="success",
                output_text="x" * 5000,
            ),
        ]

        cut_index = compaction._find_cut_index(history, start_index=0, keep_recent_tokens=200)  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(cut_index, 1)
        self.assertFalse(isinstance(history[cut_index], message.ToolResultMessage))

    def test_adjust_cut_index_skips_leading_tool_results_from_old_sessions(self) -> None:
        history: list[message.HistoryEvent] = [
            message.ToolResultMessage(
                call_id="call_1",
                tool_name="bash",
                status="success",
                output_text="ok",
            ),
            message.UserMessage(parts=[message.TextPart(text="continue")]),
        ]

        adjusted = compaction._adjust_cut_index(history, cut_index=0, start_index=0)  # pyright: ignore[reportPrivateUsage]
        self.assertEqual(adjusted, 1)
        self.assertIsInstance(history[adjusted], message.UserMessage)

    def test_session_llm_history_never_starts_with_tool_result_after_summary(self) -> None:
        sess = Session(id="test", work_dir=Path.cwd())
        sess.conversation_history = [
            message.CompactionEntry(summary="<summary>...</summary>", first_kept_index=1),
            message.ToolResultMessage(
                call_id="call_1",
                tool_name="bash",
                status="success",
                output_text="ok",
            ),
            message.UserMessage(parts=[message.TextPart(text="next")]),
        ]

        llm_history = sess.get_llm_history()
        self.assertGreaterEqual(len(llm_history), 1)
        self.assertIsInstance(llm_history[0], message.UserMessage)
        # The message immediately after the injected summary must not be a tool result.
        if len(llm_history) > 1:
            self.assertFalse(isinstance(llm_history[1], message.ToolResultMessage))

    def test_adjust_cut_index_does_not_split_tool_call_turn(self) -> None:
        """Cut must not land between an Assistant(tool_call) and its ToolResult,
        even when a DeveloperMessage sits in between. Otherwise compacted ends
        up with a dangling tool_call that gets replaced by a synthetic
        "Tool call was interrupted..." message in get_llm_history().
        """
        history: list[message.HistoryEvent] = [
            message.UserMessage(parts=[message.TextPart(text="go")]),
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(call_id="call_1", tool_name="bash", arguments_json="{}"),
                ]
            ),
            # DeveloperMessage sneaks in between call and result (e.g. attachment reminder).
            message.DeveloperMessage(parts=[message.TextPart(text="<system-reminder>memo</system-reminder>")]),
            message.ToolResultMessage(
                call_id="call_1",
                tool_name="bash",
                status="success",
                output_text="done",
            ),
            message.UserMessage(parts=[message.TextPart(text="next")]),
        ]

        # Pretend _find_cut_index picks the DeveloperMessage position.
        adjusted = compaction._adjust_cut_index(history, cut_index=2, start_index=0)  # pyright: ignore[reportPrivateUsage]

        # cut must not leave the Assistant with a dangling tool_call in compacted.
        compacted = history[:adjusted]
        answered = {it.call_id for it in compacted if isinstance(it, message.ToolResultMessage)}
        for item in compacted:
            if isinstance(item, message.AssistantMessage):
                for part in item.parts:
                    if isinstance(part, message.ToolCallPart):
                        self.assertIn(
                            part.call_id,
                            answered,
                            f"dangling tool_call {part.call_id} at cut_index={adjusted}",
                        )
        # And cut itself must not be a ToolResult (would break kept-head invariant).
        if adjusted < len(history):
            self.assertNotIsInstance(history[adjusted], message.ToolResultMessage)


if __name__ == "__main__":
    unittest.main()
