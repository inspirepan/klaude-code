"""Image generation tool implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, model, tools
from klaude_code.protocol.sub_agent import get_sub_agent_profile
from klaude_code.protocol.sub_agent.image_gen import build_image_gen_prompt
from klaude_code.session.session import Session

IMAGE_GEN_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "resume": {
            "type": "string",
            "description": "Optional agent ID to resume from. If provided, the agent will continue from the previous execution transcript.",
        },
        "description": {
            "type": "string",
            "description": "A short (3-5 word) description of the request.",
        },
        "prompt": {
            "type": "string",
            "description": "Text prompt for image generation.",
        },
        "image_paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional local image file paths used as references.",
        },
        "generation": {
            "type": "object",
            "description": "Optional per-call image generation settings.",
            "properties": {
                "aspect_ratio": {
                    "type": "string",
                    "description": "Aspect ratio, e.g. '16:9', '1:1', '9:16'.",
                },
                "image_size": {
                    "type": "string",
                    "enum": ["1K", "2K", "4K"],
                    "description": "Output size for Nano Banana Pro (must use uppercase K).",
                },
            },
            "additionalProperties": False,
        },
    },
    "required": ["prompt"],
    "additionalProperties": False,
}


@register(tools.IMAGE_GEN)
class ImageGenTool(ToolABC):
    """Generate or edit images using the ImageGen sub-agent."""

    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=True)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.IMAGE_GEN,
            type="function",
            description=load_desc(Path(__file__).parent / "image_gen.md"),
            parameters=IMAGE_GEN_PARAMETERS,
        )

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

        resume_raw = typed_args.get("resume")
        resume_session_id: str | None = None
        if isinstance(resume_raw, str) and resume_raw.strip():
            try:
                resume_session_id = Session.resolve_sub_agent_session_id(resume_raw)
            except ValueError as exc:
                return message.ToolResultMessage(status="error", output_text=str(exc))

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

        description = str(typed_args.get("description") or "")
        prompt = build_image_gen_prompt(typed_args)
        generation = typed_args.get("generation")
        generation_dict: dict[str, Any] | None = (
            cast(dict[str, Any], generation) if isinstance(generation, dict) else None
        )

        try:
            profile = get_sub_agent_profile(tools.IMAGE_GEN)
        except KeyError as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))

        try:
            result = await runner(
                model.SubAgentState(
                    sub_agent_type=profile.name,
                    sub_agent_desc=description,
                    sub_agent_prompt=prompt,
                    resume=resume_session_id,
                    output_schema=None,
                    generation=generation_dict,
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
