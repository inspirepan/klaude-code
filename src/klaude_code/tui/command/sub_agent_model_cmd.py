"""Command for changing sub-agent models."""

from __future__ import annotations

import asyncio

from klaude_code.config.config import load_config
from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper, SubAgentModelInfo
from klaude_code.protocol import commands, events, message, op
from klaude_code.tui.terminal.selector import DEFAULT_PICKER_STYLE, SelectItem, build_model_select_items, select_one

from .command_abc import Agent, CommandABC, CommandResult

USE_DEFAULT_BEHAVIOR = "__default__"


def _build_sub_agent_select_items(
    sub_agents: list[SubAgentModelInfo],
    helper: SubAgentModelHelper,
    main_model_name: str,
) -> list[SelectItem[str]]:
    """Build SelectItem list for sub-agent selection."""
    items: list[SelectItem[str]] = []
    max_name_len = max(len(sa.profile.name) for sa in sub_agents) if sub_agents else 0

    for sa in sub_agents:
        name = sa.profile.name

        if sa.configured_model:
            model_display = sa.configured_model
        else:
            behavior = helper.describe_empty_model_config_behavior(name, main_model_name=main_model_name)
            model_display = f"({behavior.description})"

        title = [
            ("class:msg", f"{name:<{max_name_len}}"),
            ("class:meta", f"  current: {model_display}\n"),
        ]
        items.append(SelectItem(title=title, value=name, search_text=name))

    return items


def _select_sub_agent_sync(
    sub_agents: list[SubAgentModelInfo],
    helper: SubAgentModelHelper,
    main_model_name: str,
) -> str | None:
    """Synchronous sub-agent type selection."""
    items = _build_sub_agent_select_items(sub_agents, helper, main_model_name)
    if not items:
        return None

    try:
        result = select_one(
            message="Select sub-agent to configure:",
            items=items,
            pointer="→",
            style=DEFAULT_PICKER_STYLE,
            use_search_filter=False,
        )
        return result if isinstance(result, str) else None
    except KeyboardInterrupt:
        return None


def _select_model_for_sub_agent_sync(
    helper: SubAgentModelHelper,
    sub_agent_type: str,
    main_model_name: str,
) -> str | None:
    """Synchronous model selection for a sub-agent."""
    models = helper.get_selectable_models(sub_agent_type)

    default_behavior = helper.describe_empty_model_config_behavior(sub_agent_type, main_model_name=main_model_name)

    inherit_item = SelectItem[str](
        title=[
            ("class:msg", "(Use default behavior)"),
            ("class:meta", f"  -> {default_behavior.description}\n"),
        ],
        value=USE_DEFAULT_BEHAVIOR,
        search_text="default unset",
    )
    model_items = build_model_select_items(models)
    all_items = [inherit_item, *model_items]

    try:
        result = select_one(
            message=f"Select model for {sub_agent_type}:",
            items=all_items,
            pointer="→",
            style=DEFAULT_PICKER_STYLE,
            use_search_filter=True,
        )
        return result if isinstance(result, str) else None
    except KeyboardInterrupt:
        return None


class SubAgentModelCommand(CommandABC):
    """Configure models for sub-agents (Task, Explore, WebAgent, ImageGen)."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.SUB_AGENT_MODEL

    @property
    def summary(self) -> str:
        return "Change sub-agent models"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        config = load_config()
        helper = SubAgentModelHelper(config)
        main_model_name = agent.get_llm_client().model_name

        sub_agents = helper.get_available_sub_agents()
        if not sub_agents:
            return CommandResult(
                events=[
                    events.CommandOutputEvent(
                        session_id=agent.session.id,
                        command_name=self.name,
                        content="No sub-agents available",
                        is_error=True,
                    )
                ]
            )

        selected_sub_agent = await asyncio.to_thread(_select_sub_agent_sync, sub_agents, helper, main_model_name)
        if selected_sub_agent is None:
            return CommandResult(
                events=[
                    events.CommandOutputEvent(
                        session_id=agent.session.id,
                        command_name=self.name,
                        content="(cancelled)",
                    )
                ]
            )

        selected_model = await asyncio.to_thread(
            _select_model_for_sub_agent_sync, helper, selected_sub_agent, main_model_name
        )
        if selected_model is None:
            return CommandResult(
                events=[
                    events.CommandOutputEvent(
                        session_id=agent.session.id,
                        command_name=self.name,
                        content="(cancelled)",
                    )
                ]
            )

        model_name: str | None = None if selected_model == USE_DEFAULT_BEHAVIOR else selected_model

        return CommandResult(
            operations=[
                op.ChangeSubAgentModelOperation(
                    session_id=agent.session.id,
                    sub_agent_type=selected_sub_agent,
                    model_name=model_name,
                    save_as_default=True,
                )
            ]
        )
