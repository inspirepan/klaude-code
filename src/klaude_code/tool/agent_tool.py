"""Agent tool implementation for running sub-agents by type."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from klaude_code.protocol import llm_param, message, model, tools
from klaude_code.protocol.sub_agent import (
    get_all_names,
    get_sub_agent_profile,
    iter_sub_agent_profiles,
)
from klaude_code.tool.context import ToolContext
from klaude_code.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.tool.tool_registry import register


def _agent_description() -> str:
    type_lines: list[str] = []
    for profile in iter_sub_agent_profiles():
        summary = profile.invoker_summary.strip()
        if summary:
            lines = summary.split("\n")
            indented = [f"- type:{profile.name}: {lines[0]}"] + ["  " + line for line in lines[1:]]
            type_lines.append("\n".join(indented))
        else:
            type_lines.append(f"- {profile.name}")

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
                "enum": get_all_names(),
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
        try:
            profile = get_sub_agent_profile(requested_type)
        except KeyError:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Unknown Agent type '{requested_type}'.",
            )

        sub_agent_prompt = str(typed_args.get("prompt", ""))

        try:
            result = await runner(
                model.SubAgentState(
                    sub_agent_type=profile.name,
                    sub_agent_desc=description,
                    sub_agent_prompt=sub_agent_prompt,
                    fork_context=profile.fork_context,
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
