"""Agent tool implementation for running sub-agents by type."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from klaude_code.config import load_config
from klaude_code.protocol import llm_param, message, tools
from klaude_code.protocol.models import SessionIdUIExtra, SubAgentState
from klaude_code.protocol.sub_agent import (
    get_all_names,
    get_sub_agent_profile,
    iter_sub_agent_profiles,
)
from klaude_code.tool.core.abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register

# The real decision tree ships in `config/assets/builtin_config.yaml` under
# `sub_agent_model_decision_tree`, so users can override it. This is only the degraded path,
# used when that key is missing or the config cannot be loaded at all -- in which case the
# available-model list is unknown too, so it deliberately names no specific model.
_FALLBACK_MODEL_DECISION_TREE = """- Omit `model` for specialized agents; their configured defaults are chosen for their roles. Pick a model only for `general-purpose` and `general-purpose-fork-context`.
- If the user asks for a specific model or provider, pass that selector exactly."""


# Single-slot cache keyed on the loaded Config object's identity. `load_config()`
# is itself cached, so the same Config instance is returned until the config is
# reloaded; holding the reference here keeps the identity stable (no id reuse).
_GUIDE_CACHE: tuple[object, str] | None = None


def _model_selection_guide() -> str:
    global _GUIDE_CACHE
    try:
        config = load_config()
    except Exception as exc:
        return (
            "Model override:\n"
            "- Optional `model` may be any configured model selector, for example `gpt-5.4-mini` "
            "or `sonnet@openrouter`.\n"
            f"- Current model list unavailable while loading config: {exc}\n\n"
            "Decision tree:\n"
            f"{_FALLBACK_MODEL_DECISION_TREE}"
        )

    cached = _GUIDE_CACHE
    if cached is not None and cached[0] is config:
        return cached[1]

    guide = _build_model_selection_guide(config)
    _GUIDE_CACHE = (config, guide)
    return guide


def _build_model_selection_guide(config: Any) -> str:
    entries = config.iter_model_entries(only_available=True, include_disabled=False)
    providers_by_model: dict[str, set[str]] = {}
    for entry in entries:
        providers_by_model.setdefault(entry.model_name, set()).add(entry.provider)

    if providers_by_model:
        available_line = ", ".join(f"`{name}`" for name in sorted(providers_by_model))
    else:
        available_line = "(no currently available configured models were found)"

    # Only models served by more than one provider are worth qualifying with `@provider`.
    # Group them by provider set so a shared tuple is spelled out once instead of per model.
    models_by_provider_set: dict[tuple[str, ...], list[str]] = {}
    for name, providers in providers_by_model.items():
        if len(providers) > 1:
            models_by_provider_set.setdefault(tuple(sorted(providers)), []).append(name)

    multi_provider_line = (
        "\n\nModels served by multiple providers: "
        + "; ".join(
            f"{', '.join(f'`{name}`' for name in sorted(models_by_provider_set[provider_set]))} "
            f"({', '.join(provider_set)})"
            for provider_set in sorted(models_by_provider_set)
        )
        if models_by_provider_set
        else ""
    )

    decision_tree = (config.sub_agent_model_decision_tree or _FALLBACK_MODEL_DECISION_TREE).strip()

    return (
        "Model override:\n"
        "- Optional `model` may be any selector below. Use an unqualified name such as `sonnet`; append "
        "`@provider` only when provider routing matters.\n"
        "- If omitted, the sub-agent uses its configured default, or inherits the main agent model when it "
        "has none.\n\n"
        f"Available models: {available_line}"
        f"{multi_provider_line}\n\n"
        "Decision tree:\n"
        f"{decision_tree}"
    )


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

    return load_desc(
        Path(__file__).parent / "agent_tool.md",
        {"types_section": types_section, "model_selection_guide": _model_selection_guide()},
    )


def _agent_schema() -> llm_param.ToolSchema:
    return llm_param.ToolSchema(
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
                "model": {
                    "type": "string",
                    "description": "Optional model selector for this sub-agent invocation, e.g. `gpt-5.4-mini` or `sonnet@openrouter`.",
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
        return _agent_schema()

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
        model_raw = typed_args.get("model")
        model = model_raw.strip() if isinstance(model_raw, str) else None

        try:
            result = await runner(
                SubAgentState(
                    sub_agent_type=profile.name,
                    sub_agent_desc=description,
                    sub_agent_prompt=sub_agent_prompt,
                    model=model or None,
                    fork_context=profile.fork_context,
                    parent_tool_batch_id=context.tool_batch_id,
                    parent_tool_batch_index=context.tool_batch_index,
                    parent_tool_batch_size=context.tool_batch_size,
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
            ui_extra=SessionIdUIExtra(session_id=result.session_id),
            task_metadata=result.task_metadata,
        )
