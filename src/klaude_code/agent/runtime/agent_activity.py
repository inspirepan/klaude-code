"""Bounded, in-memory activity facts derived from child execution events."""

import json
import time

from klaude_code.protocol import events
from klaude_code.protocol.background_task import AgentActivity, AgentToolActivity


def update_agent_activity(activity: AgentActivity | None, event: events.Event) -> AgentActivity | None:
    if not isinstance(
        event,
        events.StepStartEvent
        | events.ThinkingStartEvent
        | events.ThinkingDeltaEvent
        | events.ThinkingEndEvent
        | events.AssistantTextStartEvent
        | events.AssistantTextDeltaEvent
        | events.AssistantTextEndEvent
        | events.ResponseCompleteEvent
        | events.ToolCallStartEvent
        | events.ToolCallEvent
        | events.ToolResultEvent
        | events.ToolOutputDeltaEvent
        | events.ToolLongRunningEvent
        | events.TaskFinishEvent,
    ):
        return activity
    now = time.time()
    if activity is None:
        activity = AgentActivity(phase="waiting_model", phase_started_at=now, last_event_at=now)
    activity.last_event_at = now
    phase = activity.phase
    if isinstance(event, events.StepStartEvent | events.ThinkingEndEvent | events.AssistantTextEndEvent):
        phase = "waiting_model"
    elif isinstance(event, events.ResponseCompleteEvent):
        phase = "between_steps"
    elif isinstance(event, events.ThinkingStartEvent | events.ThinkingDeltaEvent):
        phase = "thinking"
    elif isinstance(event, events.AssistantTextStartEvent | events.AssistantTextDeltaEvent | events.ToolCallStartEvent):
        phase = "generating"
    elif isinstance(event, events.ToolCallEvent):
        try:
            arguments = json.loads(event.arguments)
        except ValueError:
            arguments = None
        if isinstance(arguments, dict):
            summary = arguments.get("command") or "; ".join(f"{key}={value}" for key, value in arguments.items())
        else:
            summary = event.arguments
        summary = " ".join(str(summary).split())
        activity.active_tools.append(
            AgentToolActivity(
                call_id=event.tool_call_id,
                name=event.tool_name,
                summary=summary[:300] + ("..." if len(summary) > 300 else ""),
                started_at=now,
            )
        )
        phase = "executing_tools"
    elif isinstance(event, events.ToolResultEvent):
        tool = next((tool for tool in activity.active_tools if tool.call_id == event.tool_call_id), None)
        if tool is not None:
            activity.active_tools.remove(tool)
            tool.ended_at = now
            tool.status = event.status
            tool.output_preview = event.result[:600] + ("..." if len(event.result) > 600 else "")
            activity.last_tool = tool
        phase = "executing_tools" if activity.active_tools else "between_steps"
    elif isinstance(event, events.TaskFinishEvent):
        phase = "finished"
        activity.active_tools.clear()
    if activity.active_tools:
        phase = "executing_tools"
    if phase != activity.phase:
        activity.phase = phase
        activity.phase_started_at = now
    return activity
