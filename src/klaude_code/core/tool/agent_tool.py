"""Agent tool implementation for running sub-agents by type."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, model, tools
from klaude_code.protocol.sub_agent import get_sub_agent_profile, iter_sub_agent_profiles

AGENT_TYPE_TO_SUB_AGENT: dict[str, str] = {
    "general-purpose": "Task",
    "explore": "Explore",
}


def _agent_description() -> str:
    summaries: dict[str, str] = {}
    for profile in iter_sub_agent_profiles():
        if profile.invoker_type:
            summaries[profile.invoker_type] = profile.invoker_summary.strip()

    type_lines: list[str] = []
    for invoker_type in AGENT_TYPE_TO_SUB_AGENT:
        summary = summaries.get(invoker_type, "")
        if summary:
            type_lines.append(f"- {invoker_type}: {summary}")
        else:
            type_lines.append(f"- {invoker_type}")

    types_section = "\n".join(type_lines) if type_lines else "- general-purpose"

    return load_desc(Path(__file__).parent / "agent_tool.md", {"types_section": types_section})


AGENT_SCHEMA = llm_param.ToolSchema(
    name=tools.AGENT,
    type="function",
    description=_agent_description(),
    parameters={
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": list(AGENT_TYPE_TO_SUB_AGENT.keys()),
                "description": "Sub-agent type selector.",
            },
            "description": {
                "type": "string",
                "description": "A short (3-5 word) description of the task. Use the same language the user is using.",
            },
            "prompt": {
                "type": "string",
                "description": "The task for the agent to perform.",
            },
            "output_schema": {
                "type": "object",
                "description": "Optional JSON Schema for structured output.",
            },
            "fork_context": {
                "type": "boolean",
                "description": "When true, fork the current thread history into the new agent before sending the initial prompt. This must be used when you want the new agent to have exactly the same context as you.",
            },
        },
        "required": ["description", "prompt"],
        "additionalProperties": False,
    },
)


@register(tools.AGENT)
class AgentTool(ToolABC):
    """Run a sub-agent based on the requested type."""

    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=True)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return AGENT_SCHEMA

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError as exc:
            return message.ToolResultMessage(status="error", output_text=f"Invalid JSON arguments: {exc}")

        if not isinstance(args, dict):
            return message.ToolResultMessage(status="error", output_text="Invalid arguments: expected object")

        typed_args = cast(dict[str, Any], args)

        runner = context.run_subtask
        if runner is None:
            return message.ToolResultMessage(
                status="error", output_text="No sub-agent runner available in this context"
            )

        description = str(typed_args.get("description") or "")

        type_raw = typed_args.get("type")
        requested_type = str(type_raw).strip() if isinstance(type_raw, str) else ""

        if not requested_type:
            requested_type = "general-purpose"
        sub_agent_type = AGENT_TYPE_TO_SUB_AGENT.get(requested_type)
        if sub_agent_type is None:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Unknown Agent type '{requested_type}'.",
            )

        try:
            profile = get_sub_agent_profile(sub_agent_type)
        except KeyError as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))

        sub_agent_prompt = profile.prompt_builder(typed_args)

        output_schema_raw = typed_args.get("output_schema")
        output_schema = cast(dict[str, Any], output_schema_raw) if isinstance(output_schema_raw, dict) else None

        fork_context = bool(typed_args.get("fork_context", False))

        try:
            result = await runner(
                model.SubAgentState(
                    sub_agent_type=profile.name,
                    sub_agent_desc=description,
                    sub_agent_prompt=sub_agent_prompt,
                    output_schema=output_schema,
                    fork_context=fork_context,
                ),
                context.record_sub_agent_session_id,
                context.register_sub_agent_metadata_getter,
                context.register_sub_agent_progress_getter,
            )
        except Exception as exc:
            return message.ToolResultMessage(status="error", output_text=f"Failed to run sub-agent: {exc}")

        return message.ToolResultMessage(
            status="success" if not result.error else "error",
            output_text=result.task_result,
            ui_extra=model.SessionIdUIExtra(session_id=result.session_id),
            task_metadata=result.task_metadata,
        )
