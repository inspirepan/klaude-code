import unittest

from klaude_code.agent.step import ToolCallRequest, build_events_from_tool_executor_event
from klaude_code.protocol import events, message
from klaude_code.tool.core.runner import ToolExecutionCallStarted, ToolExecutionResult


def test_tool_call_event_preserves_batch_metadata() -> None:
    event = ToolExecutionCallStarted(
        tool_call=ToolCallRequest(response_id="r1", call_id="c1", tool_name="Agent", arguments_json="{}"),
        tool_batch_id="r1",
        tool_batch_index=1,
        tool_batch_size=3,
    )
    translated = build_events_from_tool_executor_event("s1", event)
    assert len(translated) == 1
    launch = translated[0]
    assert isinstance(launch, events.ToolCallEvent)
    assert (launch.tool_batch_id, launch.tool_batch_index, launch.tool_batch_size) == ("r1", 1, 3)


class TestInterruptEventEmission(unittest.TestCase):
    def test_aborted_tool_result_does_not_emit_interrupt_event(self) -> None:
        tool_call = ToolCallRequest(
            response_id="r1",
            call_id="c1",
            tool_name="bash",
            arguments_json="{}",
        )
        tool_result = message.ToolResultMessage(
            call_id="c1",
            output_text="[Request interrupted by user for tool use]",
            status="aborted",
            tool_name="bash",
        )
        exec_event = ToolExecutionResult(tool_call=tool_call, tool_result=tool_result, is_last_in_step=True)

        ui_events = build_events_from_tool_executor_event("s1", exec_event)

        self.assertTrue(any(isinstance(e, events.ToolResultEvent) for e in ui_events))
        self.assertFalse(any(isinstance(e, events.InterruptEvent) for e in ui_events))
