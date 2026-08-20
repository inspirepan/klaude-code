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
        # This command runs in the client process while the server owns the
        # session. Re-read the file first: the cached copy dates from attach and
        # may miss what the server saved since (model defaults, sub-agent models).
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

        # The server caches config per process; without this it keeps serving the
        # old provider set until `klaude server reload`. Imported lazily to keep
        # the socket client out of command-registry loading.
        from klaude_code.tui.client.server_api import reload_server_config

        reload_error = await asyncio.to_thread(reload_server_config)
        changes = [f"{len(changed)} provider(s)"] if changed else []
        if search_changed:
            chain = " > ".join(selected.search_provider_names) or "(none)"
            changes.append(f"web search: {chain}")
        content = f"Provider settings saved ({'; '.join(changes)})."
        if reload_error is not None:
            content += f"\nServer still uses the old providers ({reload_error}); run: klaude server reload"
        return CommandResult(
            events=[
                events.NoticeEvent(
                    session_id=agent.session.id,
                    content=content,
                    is_error=reload_error is not None,
                )
            ]
        )
