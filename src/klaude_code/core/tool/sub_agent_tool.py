"""Generic sub-agent tool implementation.

This module provides a single tool class that can handle all sub-agent invocations
based on their SubAgentProfile configuration.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, ClassVar, cast

from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata
from klaude_code.core.tool.tool_context import current_run_subtask_callback, current_sub_agent_resume_claims
from klaude_code.protocol import llm_param, model
from klaude_code.session.session import Session

if TYPE_CHECKING:
    from klaude_code.protocol.sub_agent import SubAgentProfile


class SubAgentTool(ToolABC):
    """Generic tool implementation for all sub-agents.

    Each sub-agent type gets its own dynamically generated subclass with the
    appropriate profile attached as a class variable.
    """

    _profile: ClassVar[SubAgentProfile]

    @classmethod
    def for_profile(cls, profile: SubAgentProfile) -> type[SubAgentTool]:
        """Create a tool class for a specific sub-agent profile."""
        return type(
            f"{profile.name}Tool",
            (SubAgentTool,),
            {"_profile": profile},
        )

    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=True)

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        profile = cls._profile
        return llm_param.ToolSchema(
            name=profile.name,
            type="function",
            description=profile.description,
            parameters=profile.parameters,
        )

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        profile = cls._profile

        try:
            args = json.loads(arguments)
        except json.JSONDecodeError as e:
            return model.ToolResultItem(status="error", output=f"Invalid JSON arguments: {e}")

        runner = current_run_subtask_callback.get()
        if runner is None:
            return model.ToolResultItem(status="error", output="No subtask runner available in this context")

        # Build the prompt using the profile's prompt builder
        prompt = profile.prompt_builder(args)
        description = args.get("description", "")

        resume_raw = args.get("resume")
        resume_session_id: str | None = None
        if isinstance(resume_raw, str) and resume_raw.strip():
            try:
                resume_session_id = Session.resolve_sub_agent_session_id(resume_raw)
            except ValueError as exc:
                return model.ToolResultItem(status="error", output=str(exc))

            claims = current_sub_agent_resume_claims.get()
            if claims is not None:
                if resume_session_id in claims:
                    return model.ToolResultItem(
                        status="error",
                        output=(
                            "Duplicate sub-agent resume in the same response: "
                            f"resume='{resume_raw.strip()}' (resolved='{resume_session_id[:7]}...'). "
                            "Merge into a single call or resume in a later turn."
                        ),
                    )
                claims.add(resume_session_id)

        generation = args.get("generation")
        generation_dict: dict[str, Any] | None = (
            cast(dict[str, Any], generation) if isinstance(generation, dict) else None
        )

        # Extract output_schema if configured
        output_schema = None
        if profile.output_schema_arg:
            output_schema = args.get(profile.output_schema_arg)

        try:
            result = await runner(
                model.SubAgentState(
                    sub_agent_type=profile.name,
                    sub_agent_desc=description,
                    sub_agent_prompt=prompt,
                    resume=resume_session_id,
                    output_schema=output_schema,
                    generation=generation_dict,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return model.ToolResultItem(status="error", output=f"Failed to run subtask: {e}")

        task_result = result.task_result or ""
        if result.session_id and "agentId:" not in task_result:
            task_result = (
                task_result.rstrip()
                + ("\n\n" if task_result.strip() else "")
                + f"agentId: {result.session_id} (for resuming to continue this agent's work if needed)"
            )

        return model.ToolResultItem(
            status="success" if not result.error else "error",
            output=task_result,
            ui_extra=model.SessionIdUIExtra(session_id=result.session_id),
            task_metadata=result.task_metadata,
        )
