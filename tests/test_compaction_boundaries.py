import unittest
from pathlib import Path

from klaude_code.core.compaction import compaction
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

        cut_index = compaction._find_cut_index(history, start_index=0, keep_recent_tokens=200)
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

        adjusted = compaction._adjust_cut_index(history, cut_index=0, start_index=0)
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


if __name__ == "__main__":
    unittest.main()
