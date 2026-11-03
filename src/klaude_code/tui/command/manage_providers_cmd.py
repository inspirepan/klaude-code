"""Provider management slash command."""

import asyncio

from klaude_code.config.loader import load_config
from klaude_code.protocol import events, message

from .command_abc import Agent, CommandABC, CommandResult
from .provider_manager import (
    build_provider_states,
    build_search_provider_states,
    build_web_search_config,
    manage_providers_interactive,
)
from .types import CommandName


class ManageProvidersCommand(CommandABC):
    """Enable or disable configured providers."""

    @property
    def name(self) -> CommandName:
        return CommandName.MANAGE_PROVIDERS

    @property
    def summary(self) -> str:
        return "Enable or disable providers"

    @property
    def is_interactive(self) -> bool:
        return True

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        del user_input
        # Re-read the file so this edit includes changes from other processes.
        load_config.cache_clear()
        config = load_config()
        states = build_provider_states(config)
        search_states = build_search_provider_states(config)
        if not states and not search_states:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content="No configured providers to manage.",
                    )
                ]
            )
        selected = await asyncio.to_thread(manage_providers_interactive, states, search_states)
        if selected is None:
            return CommandResult(events=[events.NoticeEvent(session_id=agent.session.id, content="(cancelled)")])

        changed = [state for state in states if selected.disabled_by_name[state.name] != state.disabled]
        current_search_names = [state.name for state in search_states if state.enabled]
        search_changed = selected.search_provider_names != current_search_names
        if not changed and not search_changed:
            return CommandResult(
                events=[events.NoticeEvent(session_id=agent.session.id, content="No provider changes.")]
            )

        try:
            candidate = config.model_copy(deep=True)
            for state in changed:
                candidate.set_provider_disabled(state.name, selected.disabled_by_name[state.name])
            if search_changed:
                candidate.web_search = build_web_search_config(config, selected.search_provider_names)
            await candidate.save()
        except (OSError, ValueError) as exc:
            return CommandResult(
                events=[
                    events.NoticeEvent(
                        session_id=agent.session.id,
                        content=f"Failed to save provider settings: {exc}",
                        is_error=True,
                    )
                ]
            )

        for state in changed:
            config.set_provider_disabled(state.name, selected.disabled_by_name[state.name])
        if search_changed:
            config.web_search = candidate.web_search
        load_config.cache_clear()

        changes = [f"{len(changed)} provider(s)"] if changed else []
        if search_changed:
            chain = " > ".join(selected.search_provider_names) or "(none)"
            changes.append(f"web search: {chain}")
        content = f"Provider settings saved ({'; '.join(changes)})."
        return CommandResult(
            events=[
                events.NoticeEvent(
                    session_id=agent.session.id,
                    content=content,
                )
            ]
        )
