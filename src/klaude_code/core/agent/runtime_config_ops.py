"""Model switching and configuration change operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from klaude_code.config import format_model_preference, load_config
from klaude_code.config.model_matcher import match_model_from_config
from klaude_code.config.sub_agent_model_helper import SubAgentModelHelper
from klaude_code.config.thinking import get_thinking_picker_data, parse_thinking_value
from klaude_code.core.agent.agent import Agent
from klaude_code.core.agent.runtime_agent_ops import AgentRunner
from klaude_code.core.agent_profile import ModelProfileProvider
from klaude_code.core.session_stats import build_session_stats_ui_extra
from klaude_code.llm.registry import create_llm_client
from klaude_code.protocol import events, op, user_interaction
from klaude_code.protocol.llm_param import LLMConfigParameter, Thinking
from klaude_code.protocol.sub_agent import get_sub_agent_profile


class ModelSwitcher:
    """Apply model changes to an agent session."""

    def __init__(self, model_profile_provider: ModelProfileProvider) -> None:
        self._model_profile_provider = model_profile_provider

    async def change_model(
        self,
        agent: Agent,
        *,
        model_name: str,
        save_as_default: bool,
    ) -> tuple[LLMConfigParameter, str]:
        config = load_config()
        llm_config = config.get_model_config(model_name)
        llm_client = create_llm_client(llm_config)
        agent.set_model_profile(self._model_profile_provider.build_profile(llm_client, work_dir=agent.session.work_dir))

        agent.session.model_config_name = model_name
        agent.session.model_thinking = llm_config.thinking

        if save_as_default:
            config.main_model = model_name
            await config.save()

        return llm_config, model_name

    def change_thinking(self, agent: Agent, *, thinking: Thinking) -> Thinking | None:
        """Apply thinking configuration to the agent's active LLM config and persisted session."""

        config = agent.profile.llm_client.get_llm_config()
        previous = config.thinking
        config.thinking = thinking
        agent.session.model_thinking = thinking
        return previous


class ConfigHandler:
    def __init__(
        self,
        *,
        agent_runner: AgentRunner,
        model_switcher: ModelSwitcher,
        emit_event: Callable[[events.Event], Awaitable[None]],
        request_user_interaction: Callable[
            [str, str, user_interaction.UserInteractionSource, user_interaction.UserInteractionRequestPayload],
            Awaitable[user_interaction.UserInteractionResponse],
        ],
        current_session_id: Callable[[], str | None],
        on_model_change: Callable[[str], None] | None,
    ) -> None:
        self._agent_runner = agent_runner
        self._model_switcher = model_switcher
        self._emit_event = emit_event
        self._request_user_interaction = request_user_interaction
        self._current_session_id = current_session_id
        self._on_model_change = on_model_change

    @staticmethod
    def _format_thinking_for_display(thinking: Thinking | None) -> str:
        if thinking is None:
            return "not configured"
        if thinking.reasoning_effort:
            return f"reasoning_effort={thinking.reasoning_effort}"
        if thinking.type == "disabled":
            return "off"
        if thinking.type == "enabled":
            if thinking.budget_tokens is None:
                return "enabled"
            return f"enabled (budget_tokens={thinking.budget_tokens})"
        return "not set"

    async def handle_change_model(self, operation: op.ChangeModelOperation) -> None:
        agent = await self._agent_runner.ensure_agent(operation.session_id)
        llm_config, llm_client_name = await self._model_switcher.change_model(
            agent,
            model_name=operation.model_name,
            save_as_default=operation.save_as_default,
        )
        self._agent_runner.set_session_main_client(
            session_id=agent.session.id,
            client=agent.profile.llm_client,
            model_alias=llm_client_name,
        )

        if operation.emit_switch_message:
            await self._emit_event(
                events.ModelChangedEvent(
                    session_id=agent.session.id,
                    model_id=llm_config.model_id or llm_client_name,
                    saved_as_default=operation.save_as_default,
                )
            )

        if self._on_model_change is not None and self._current_session_id() == agent.session.id:
            self._on_model_change(llm_client_name)

        if operation.emit_welcome_event:
            await self._emit_event(
                events.WelcomeEvent(
                    session_id=agent.session.id,
                    llm_config=llm_config,
                    work_dir=str(agent.session.work_dir),
                    title=agent.session.title,
                    show_klaude_code_info=False,
                )
            )

    async def handle_change_thinking(self, operation: op.ChangeThinkingOperation) -> None:
        agent = await self._agent_runner.ensure_agent(operation.session_id)

        if operation.thinking is None:
            raise ValueError("thinking must be provided; interactive selection belongs to UI")

        previous = self._model_switcher.change_thinking(agent, thinking=operation.thinking)
        current = self._format_thinking_for_display(previous)
        new_status = self._format_thinking_for_display(operation.thinking)

        if operation.emit_switch_message:
            await self._emit_event(
                events.ThinkingChangedEvent(
                    session_id=agent.session.id,
                    previous=current,
                    current=new_status,
                )
            )

        if operation.emit_welcome_event:
            await self._emit_event(
                events.WelcomeEvent(
                    session_id=agent.session.id,
                    work_dir=str(agent.session.work_dir),
                    llm_config=agent.profile.llm_client.get_llm_config(),
                    title=agent.session.title,
                    show_klaude_code_info=False,
                )
            )

    async def handle_change_sub_agent_model(self, operation: op.ChangeSubAgentModelOperation) -> None:
        agent = await self._agent_runner.ensure_agent(operation.session_id)
        session_clients = self._agent_runner.get_session_llm_clients(agent.session.id)
        config = load_config()

        helper = SubAgentModelHelper(config)
        sub_agent_type = operation.sub_agent_type
        model_name = operation.model_name

        if model_name is None:
            behavior = helper.describe_empty_model_config_behavior(
                sub_agent_type,
                main_model_name=session_clients.main.model_name,
            )
            session_clients.sub_clients.pop(sub_agent_type, None)
            display_model = f"({behavior.description})"
        else:
            llm_config = config.get_model_config(model_name)
            new_client = create_llm_client(llm_config)
            session_clients.sub_clients[sub_agent_type] = new_client
            display_model = new_client.model_name

        if operation.save_as_default:
            profile = get_sub_agent_profile(sub_agent_type)
            role_key = profile.name
            if model_name is None:
                config.sub_agent_models.pop(role_key, None)
            else:
                config.sub_agent_models[role_key] = model_name
            await config.save()

        saved_note = " (saved in ~/.klaude/klaude-config.yaml)" if operation.save_as_default else ""
        await self._emit_event(
            events.SubAgentModelChangedEvent(
                session_id=agent.session.id,
                sub_agent_type=sub_agent_type,
                model_display=f"{display_model}{saved_note}",
                saved_as_default=operation.save_as_default,
            )
        )

    async def handle_change_compact_model(self, operation: op.ChangeCompactModelOperation) -> None:
        agent = await self._agent_runner.ensure_agent(operation.session_id)
        session_clients = self._agent_runner.get_session_llm_clients(agent.session.id)
        config = load_config()

        model_name = operation.model_name
        if model_name is None:
            session_clients.compact = None
            agent.compact_llm_client = None
            display_model = "(inherit from main agent)"
        else:
            llm_config = config.get_model_config(model_name)
            new_client = create_llm_client(llm_config)
            session_clients.compact = new_client
            agent.compact_llm_client = new_client
            display_model = new_client.model_name

        if operation.save_as_default:
            config.compact_model = model_name
            await config.save()

        saved_note = " (saved in ~/.klaude/klaude-config.yaml)" if operation.save_as_default else ""
        await self._emit_event(
            events.CompactModelChangedEvent(
                session_id=agent.session.id,
                model_display=f"{display_model}{saved_note}",
                saved_as_default=operation.save_as_default,
            )
        )

    async def _ask_single_choice(
        self,
        *,
        session_id: str,
        source: user_interaction.UserInteractionSource,
        header: str,
        question: str,
        options: list[user_interaction.OperationSelectOption],
        input_placeholder: str | None = None,
    ) -> str | None:
        payload = user_interaction.OperationSelectRequestPayload(
            header=header,
            question=question,
            options=options,
            input_placeholder=input_placeholder,
        )
        response = await self._request_user_interaction(session_id, uuid4().hex, source, payload)
        if response.status != "submitted" or response.payload is None:
            return None
        if response.payload.kind != "operation_select":
            return None
        return response.payload.selected_option_id

    async def handle_request_model(self, operation: op.RequestModelOperation) -> None:
        async def _runner() -> None:
            match = match_model_from_config(operation.preferred)
            if match.error_message:
                await self._emit_event(
                    events.NoticeEvent(
                        session_id=operation.session_id,
                        content=match.error_message,
                        is_error=True,
                    )
                )
                return

            selected_model = match.matched_model
            if selected_model is None:
                options = [
                    user_interaction.OperationSelectOption(
                        id=entry.selector,
                        label=entry.selector,
                        description=f"{entry.provider} / {entry.model_id or entry.model_name}",
                    )
                    for entry in match.filtered_models
                ]
                if not options:
                    await self._emit_event(
                        events.NoticeEvent(
                            session_id=operation.session_id,
                            content="No models available.",
                            is_error=True,
                        )
                    )
                    return
                filtered = f" (filtered by '{match.filter_hint}')" if match.filter_hint else ""
                selected_model = await self._ask_single_choice(
                    session_id=operation.session_id,
                    source="operation_model",
                    header="Model",
                    question=f"Select a model ({len(options)}){filtered}:",
                    options=options,
                )

            if selected_model is None:
                await self._emit_event(events.NoticeEvent(session_id=operation.session_id, content="(no change)"))
                return

            agent = await self._agent_runner.ensure_agent(operation.session_id)
            if selected_model == agent.session.model_config_name:
                await self._emit_event(events.NoticeEvent(session_id=operation.session_id, content="(no change)"))
                return

            await self.handle_change_model(
                op.ChangeModelOperation(
                    session_id=operation.session_id,
                    model_name=selected_model,
                    save_as_default=operation.save_as_default,
                    defer_thinking_selection=operation.defer_thinking_selection,
                    emit_welcome_event=operation.emit_welcome_event,
                    emit_switch_message=operation.emit_switch_message,
                )
            )

        await self._agent_runner.run_background_operation(
            operation_id=operation.id,
            session_id=operation.session_id,
            runner=_runner,
        )

    async def handle_request_thinking(self, operation: op.RequestThinkingOperation) -> None:
        async def _runner() -> None:
            agent = await self._agent_runner.ensure_agent(operation.session_id)
            llm_config = agent.profile.llm_client.get_llm_config()
            picker_data = get_thinking_picker_data(llm_config)
            if picker_data is None:
                await self._emit_event(
                    events.NoticeEvent(
                        session_id=operation.session_id,
                        content="Thinking configuration is not available for current model.",
                        is_error=True,
                    )
                )
                return

            options = [
                user_interaction.OperationSelectOption(
                    id=option.value,
                    label=option.label,
                    description="",
                )
                for option in picker_data.options
            ]
            selected = await self._ask_single_choice(
                session_id=operation.session_id,
                source="operation_thinking",
                header="Thinking",
                question=picker_data.message,
                options=options,
            )
            if selected is None:
                await self._emit_event(events.NoticeEvent(session_id=operation.session_id, content="(no change)"))
                return

            thinking = parse_thinking_value(selected)
            if thinking is None:
                await self._emit_event(
                    events.NoticeEvent(
                        session_id=operation.session_id,
                        content="Invalid thinking option selected.",
                        is_error=True,
                    )
                )
                return

            if llm_config.thinking == thinking:
                await self._emit_event(events.NoticeEvent(session_id=operation.session_id, content="(no change)"))
                return

            await self.handle_change_thinking(
                op.ChangeThinkingOperation(
                    session_id=operation.session_id,
                    thinking=thinking,
                    emit_welcome_event=operation.emit_welcome_event,
                    emit_switch_message=operation.emit_switch_message,
                )
            )

        await self._agent_runner.run_background_operation(
            operation_id=operation.id,
            session_id=operation.session_id,
            runner=_runner,
        )

    async def handle_request_sub_agent_model(self, operation: op.RequestSubAgentModelOperation) -> None:
        async def _runner() -> None:
            agent = await self._agent_runner.ensure_agent(operation.session_id)
            session_clients = self._agent_runner.get_session_llm_clients(agent.session.id)
            config = load_config()
            helper = SubAgentModelHelper(config)
            main_model_name = session_clients.main.model_name

            target_options: list[user_interaction.OperationSelectOption] = [
                user_interaction.OperationSelectOption(
                    id="__compact__",
                    label="Compact",
                    description=format_model_preference(config.compact_model)
                    or f"(inherit from main agent: {main_model_name})",
                ),
                user_interaction.OperationSelectOption(
                    id="__fast__",
                    label="Fast",
                    description=format_model_preference(config.fast_model)
                    or f"(inherit from main agent: {main_model_name})",
                ),
            ]
            for sub_agent in helper.get_available_sub_agents():
                if sub_agent.configured_model:
                    model_display = format_model_preference(sub_agent.configured_model) or ""
                else:
                    behavior = helper.describe_empty_model_config_behavior(
                        sub_agent.profile.name,
                        main_model_name=main_model_name,
                    )
                    model_display = f"({behavior.description})"
                target_options.append(
                    user_interaction.OperationSelectOption(
                        id=sub_agent.profile.name,
                        label=sub_agent.profile.name,
                        description=model_display,
                    )
                )

            target = await self._ask_single_choice(
                session_id=operation.session_id,
                source="operation_sub_agent_model",
                header="Sub-Agent",
                question="Select sub-agent to configure:",
                options=target_options,
            )
            if target is None:
                await self._emit_event(events.NoticeEvent(session_id=operation.session_id, content="(no change)"))
                return

            if target == "__compact__":
                compact_options = [
                    user_interaction.OperationSelectOption(
                        id="__default__",
                        label="(Use default behavior)",
                        description=f"inherit from main agent: {main_model_name}",
                    )
                ]
                for entry in config.iter_model_entries(only_available=True, include_disabled=False):
                    compact_options.append(
                        user_interaction.OperationSelectOption(
                            id=entry.selector,
                            label=entry.selector,
                            description=f"{entry.provider} / {entry.model_id or entry.model_name}",
                        )
                    )

                selected_model = await self._ask_single_choice(
                    session_id=operation.session_id,
                    source="operation_model",
                    header="Compact",
                    question="Select model for Compact:",
                    options=compact_options,
                )
                if selected_model is None:
                    await self._emit_event(events.NoticeEvent(session_id=operation.session_id, content="(no change)"))
                    return

                await self.handle_change_compact_model(
                    op.ChangeCompactModelOperation(
                        session_id=operation.session_id,
                        model_name=None if selected_model == "__default__" else selected_model,
                        save_as_default=operation.save_as_default,
                    )
                )
                return

            if target == "__fast__":
                fast_options = [
                    user_interaction.OperationSelectOption(
                        id="__default__",
                        label="(Use default behavior)",
                        description=f"inherit from main agent: {main_model_name}",
                    )
                ]
                for entry in config.iter_model_entries(only_available=True, include_disabled=False):
                    fast_options.append(
                        user_interaction.OperationSelectOption(
                            id=entry.selector,
                            label=entry.selector,
                            description=f"{entry.provider} / {entry.model_id or entry.model_name}",
                        )
                    )

                selected_model = await self._ask_single_choice(
                    session_id=operation.session_id,
                    source="operation_model",
                    header="Fast",
                    question="Select model for Fast:",
                    options=fast_options,
                )
                if selected_model is None:
                    await self._emit_event(events.NoticeEvent(session_id=operation.session_id, content="(no change)"))
                    return

                if selected_model == "__default__":
                    session_clients.fast = None
                    display_model = "(inherit from main agent)"
                    config_model: str | None = None
                else:
                    llm_config = config.get_model_config(selected_model)
                    new_client = create_llm_client(llm_config)
                    session_clients.fast = new_client
                    display_model = new_client.model_name
                    config_model = selected_model

                if operation.save_as_default:
                    config.fast_model = config_model
                    await config.save()

                saved_note = " (saved in ~/.klaude/klaude-config.yaml)" if operation.save_as_default else ""
                await self._emit_event(
                    events.NoticeEvent(
                        session_id=operation.session_id,
                        content=f"Fast model: {display_model}{saved_note}",
                    )
                )
                return

            default_behavior = helper.describe_empty_model_config_behavior(target, main_model_name=main_model_name)
            sub_model_options = [
                user_interaction.OperationSelectOption(
                    id="__default__",
                    label="(Use default behavior)",
                    description=f"-> {default_behavior.description}",
                )
            ]
            for entry in helper.get_selectable_models(target):
                sub_model_options.append(
                    user_interaction.OperationSelectOption(
                        id=entry.selector,
                        label=entry.selector,
                        description=f"{entry.provider} / {entry.model_id or entry.model_name}",
                    )
                )

            selected_model = await self._ask_single_choice(
                session_id=operation.session_id,
                source="operation_model",
                header=target,
                question=f"Select model for {target}:",
                options=sub_model_options,
            )
            if selected_model is None:
                await self._emit_event(events.NoticeEvent(session_id=operation.session_id, content="(no change)"))
                return

            await self.handle_change_sub_agent_model(
                op.ChangeSubAgentModelOperation(
                    session_id=operation.session_id,
                    sub_agent_type=target,
                    model_name=None if selected_model == "__default__" else selected_model,
                    save_as_default=operation.save_as_default,
                )
            )

        await self._agent_runner.run_background_operation(
            operation_id=operation.id,
            session_id=operation.session_id,
            runner=_runner,
        )

    async def handle_get_session_stats(self, operation: op.GetSessionStatsOperation) -> None:
        agent = await self._agent_runner.ensure_agent(operation.session_id)
        await self._emit_event(
            events.SessionStatsEvent(
                session_id=agent.session.id,
                stats=build_session_stats_ui_extra(agent.session),
            )
        )
