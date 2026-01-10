"""Task tool implementation for running sub-agents by type."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, model, tools
from klaude_code.protocol.sub_agent import get_sub_agent_profile, iter_sub_agent_profiles
from klaude_code.session.session import Session

TASK_TYPE_TO_SUB_AGENT: dict[str, str] = {
    "general-purpose": "Task",
    "explore": "Explore",
    "web": "Web",
}


def _task_description() -> str:
    summaries: dict[str, str] = {}
    for profile in iter_sub_agent_profiles():
        if profile.invoker_type:
            summaries[profile.invoker_type] = profile.invoker_summary.strip()

    type_lines: list[str] = []
    for invoker_type in TASK_TYPE_TO_SUB_AGENT:
        summary = summaries.get(invoker_type, "")
        if summary:
            type_lines.append(f"- {invoker_type}: {summary}")
        else:
            type_lines.append(f"- {invoker_type}")

    types_section = "\n".join(type_lines) if type_lines else "- general-purpose"

    return load_desc(Path(__file__).parent / "task.md", {"types_section": types_section})


TASK_SCHEMA = llm_param.ToolSchema(
    name=tools.TASK,
    type="function",
    description=_task_description(),
    parameters={
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": list(TASK_TYPE_TO_SUB_AGENT.keys()),
                "description": "Sub-agent type selector.",
            },
            "description": {
                "type": "string",
                "description": "A short (3-5 word) description of the task.",
            },
            "prompt": {
                "type": "string",
                "description": "The task for the agent to perform.",
            },
            "output_schema": {
                "type": "object",
                "description": "Optional JSON Schema for structured output.",
            },
            "resume": {
                "type": "string",
                "description": "Optional agent ID to resume from.",
            },
        },
        "required": ["description", "prompt"],
        "additionalProperties": False,
    },
)


@register(tools.TASK)
class TaskTool(ToolABC):
    """Run a sub-agent based on the requested type."""

    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=True)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return TASK_SCHEMA

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
            return message.ToolResultMessage(status="error", output_text="No subtask runner available in this context")

        description = str(typed_args.get("description") or "")

        resume_raw = typed_args.get("resume")
        resume_session_id: str | None = None
        resume_sub_agent_type: str | None = None
        if isinstance(resume_raw, str) and resume_raw.strip():
            try:
                resume_session_id = Session.resolve_sub_agent_session_id(resume_raw)
            except ValueError as exc:
                return message.ToolResultMessage(status="error", output_text=str(exc))

            try:
                resume_session = Session.load(resume_session_id)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return message.ToolResultMessage(
                    status="error",
                    output_text=f"Failed to resume sub-agent session '{resume_session_id}': {exc}",
                )

            if resume_session.sub_agent_state is None:
                return message.ToolResultMessage(
                    status="error",
                    output_text=f"Invalid resume id '{resume_session_id}': target session is not a sub-agent session",
                )

            resume_sub_agent_type = resume_session.sub_agent_state.sub_agent_type
            if resume_sub_agent_type == tools.IMAGE_GEN:
                return message.ToolResultMessage(
                    status="error",
                    output_text="This resume id belongs to ImageGen; use the ImageGen tool to resume it.",
                )

            claims = context.sub_agent_resume_claims
            if claims is not None:
                ok = await claims.claim(resume_session_id)
                if not ok:
                    return message.ToolResultMessage(
                        status="error",
                        output_text=(
                            "Duplicate sub-agent resume in the same response: "
                            f"resume='{resume_raw.strip()}' (resolved='{resume_session_id[:7]}…'). "
                            "Merge into a single call or resume in a later turn."
                        ),
                    )

        type_raw = typed_args.get("type")
        requested_type = str(type_raw).strip() if isinstance(type_raw, str) else ""

        if resume_session_id and not requested_type:
            sub_agent_type = resume_sub_agent_type or TASK_TYPE_TO_SUB_AGENT["general-purpose"]
        else:
            if not requested_type:
                requested_type = "general-purpose"
            sub_agent_type = TASK_TYPE_TO_SUB_AGENT.get(requested_type)
            if sub_agent_type is None:
                return message.ToolResultMessage(
                    status="error",
                    output_text=f"Unknown Task type '{requested_type}'.",
                )

        if resume_session_id and resume_sub_agent_type and resume_sub_agent_type != sub_agent_type:
            return message.ToolResultMessage(
                status="error",
                output_text=(
                    "Invalid resume id: sub-agent type mismatch. "
                    f"Expected '{sub_agent_type}', got '{resume_sub_agent_type}'."
                ),
            )

        try:
            profile = get_sub_agent_profile(sub_agent_type)
        except KeyError as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))

        sub_agent_prompt = profile.prompt_builder(typed_args)

        output_schema_raw = typed_args.get("output_schema")
        output_schema = cast(dict[str, Any], output_schema_raw) if isinstance(output_schema_raw, dict) else None

        try:
            result = await runner(
                model.SubAgentState(
                    sub_agent_type=profile.name,
                    sub_agent_desc=description,
                    sub_agent_prompt=sub_agent_prompt,
                    resume=resume_session_id,
                    output_schema=output_schema,
                    generation=None,
                ),
                context.record_sub_agent_session_id,
                context.register_sub_agent_metadata_getter,
            )
        except Exception as exc:
            return message.ToolResultMessage(status="error", output_text=f"Failed to run subtask: {exc}")

        return message.ToolResultMessage(
            status="success" if not result.error else "error",
            output_text=result.task_result,
            ui_extra=model.SessionIdUIExtra(session_id=result.session_id),
            task_metadata=result.task_metadata,
        )
