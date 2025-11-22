from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from klaude_code.core.prompt import get_system_prompt as load_system_prompt
from klaude_code.core.reminders import (
    Reminder,
    get_main_agent_reminders,
    get_sub_agent_reminders,
    get_vanilla_reminders,
)
from klaude_code.core.sub_agent import get_sub_agent_profile, is_sub_agent_tool
from klaude_code.core.tool.tool_context import current_session_var
from klaude_code.core.tool.tool_registry import get_main_agent_tools, get_sub_agent_tools, get_vanilla_tools, run_tool
from klaude_code.llm.client import LLMClientABC
from klaude_code.protocol import events, llm_parameter, model, tools
from klaude_code.session import Session
from klaude_code.trace import log_debug

# Constant for cancellation message
CANCEL_OUTPUT = "[Request interrupted by user for tool use]"
FIRST_EVENT_TIMEOUT_S = 200.0
MAX_FAILED_TURN_RETRIES = 10
INITIAL_RETRY_DELAY_S = 1.0
MAX_RETRY_DELAY_S = 30.0


@dataclass
class AgentLLMClients:
    main: LLMClientABC
    fast: LLMClientABC | None = None  # Not used for now
    sub_clients: dict[tools.SubAgentType, LLMClientABC | None] = field(
        default_factory=lambda: cast(dict[tools.SubAgentType, LLMClientABC | None], {})
    )

    def get_sub_agent_client(self, sub_agent_type: tools.SubAgentType) -> LLMClientABC:
        return self.sub_clients.get(sub_agent_type) or self.main

    def set_sub_agent_client(self, sub_agent_type: tools.SubAgentType, client: LLMClientABC) -> None:
        self.sub_clients[sub_agent_type] = client


@dataclass
class UnfinishedToolCallItem:
    """Tracks an inflight tool call and its execution status."""

    tool_call_item: model.ToolCallItem
    status: Literal["pending", "in_progress"]


@dataclass
class _MetadataMergeState:
    accumulated: "model.ResponseMetadataItem"
    throughput_weighted_sum: float = 0.0
    throughput_tracked_tokens: int = 0


@dataclass(frozen=True)
class AgentRole:
    """Defines the role context when configuring an agent."""

    name: Literal["main", "sub"]
    sub_agent_type: tools.SubAgentType | None = None

    @classmethod
    def main(cls) -> "AgentRole":
        return cls(name="main")

    @classmethod
    def sub(cls, sub_agent_type: tools.SubAgentType) -> "AgentRole":
        return cls(name="sub", sub_agent_type=sub_agent_type)

    def require_sub_agent_type(self) -> tools.SubAgentType:
        if self.sub_agent_type is None:
            raise ValueError("Sub-agent role requires sub_agent_type")
        return self.sub_agent_type


@dataclass(frozen=True)
class AgentProfile:
    """Encapsulates the active LLM client plus prompt/tools/reminders."""

    llm_client: LLMClientABC
    role: AgentRole
    system_prompt: str | None
    tools: list[llm_parameter.ToolSchema]
    reminders: list[Reminder]


class ModelProfileProvider(Protocol):
    """Strategy interface for constructing agent profiles."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        agent_role: AgentRole,
    ) -> AgentProfile: ...


class DefaultModelProfileProvider(ModelProfileProvider):
    """Default provider backed by global prompt/tool/reminder registries."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        agent_role: AgentRole,
    ) -> AgentProfile:
        model_name = llm_client.model_name

        if agent_role.name == "main":
            prompt_key = "main"
        else:
            prompt_key = get_sub_agent_profile(agent_role.require_sub_agent_type()).prompt_key
        system_prompt = load_system_prompt(model_name, prompt_key)

        if agent_role.name == "main":
            tools = get_main_agent_tools(model_name)
            reminders = get_main_agent_reminders(model_name)
        else:
            sub_agent_type = agent_role.require_sub_agent_type()
            tools = get_sub_agent_tools(model_name, sub_agent_type)
            reminders = get_sub_agent_reminders(model_name)

        return AgentProfile(
            llm_client=llm_client,
            role=agent_role,
            system_prompt=system_prompt,
            tools=tools,
            reminders=reminders,
        )


class VanillaModelProfileProvider(ModelProfileProvider):
    """Provider that strips prompts, reminders, and tools for vanilla mode."""

    def build_profile(
        self,
        llm_client: LLMClientABC,
        agent_role: AgentRole,
    ) -> AgentProfile:
        return AgentProfile(
            llm_client=llm_client,
            role=agent_role,
            system_prompt=None,
            tools=get_vanilla_tools(),
            reminders=get_vanilla_reminders(),
        )


class Agent:
    def __init__(
        self,
        llm_clients: AgentLLMClients,
        session: Session,
        initial_profile: AgentProfile,
        *,
        model_profile_provider: ModelProfileProvider | None = None,
    ):
        self.session: Session = session
        self.llm_clients = llm_clients
        self.model_profile_provider: ModelProfileProvider = model_profile_provider or DefaultModelProfileProvider()
        self.profile: AgentProfile | None = None
        # Track tool calls that are pending or in-progress within the current turn
        # Keyed by tool_call_id
        self.turn_inflight_tool_calls: dict[str, UnfinishedToolCallItem] = {}
        # Ensure runtime configuration matches the active model on initialization
        self.set_model_profile(initial_profile)

    def cancel(self) -> Iterable[events.Event]:
        """Handle agent cancellation and persist an interrupt marker and tool cancellations.

        - Appends an `InterruptItem` into the session history so interruptions are reflected
          in persisted conversation logs.
        - For any tool calls that are pending or in-progress in the current turn, append a
          synthetic ToolResultItem with error status to indicate cancellation.
        """
        # Persist cancel results for pending tool calls
        if self.turn_inflight_tool_calls:
            for _, unfinished in list(self.turn_inflight_tool_calls.items()):
                # Create synthetic error result for cancellation
                tc = unfinished.tool_call_item
                cancel_result = model.ToolResultItem(
                    call_id=tc.call_id,
                    output=CANCEL_OUTPUT,
                    status="error",
                    tool_name=tc.name,
                    ui_extra=None,
                )
                if unfinished.status == "pending":
                    # Emit ToolCallEvent for pending calls before error result
                    yield events.ToolCallEvent(
                        session_id=self.session.id,
                        response_id=tc.response_id,
                        tool_call_id=tc.call_id,
                        tool_name=tc.name,
                        arguments=tc.arguments,
                    )
                yield events.ToolResultEvent(
                    session_id=self.session.id,
                    response_id=tc.response_id,
                    tool_call_id=tc.call_id,
                    tool_name=tc.name,
                    result=CANCEL_OUTPUT,
                    status="error",
                )
                self.session.append_history([cancel_result])
            # Clear pending map after recording cancellations
            self.turn_inflight_tool_calls.clear()

        # Record an interrupt marker in the session history
        self.session.append_history([model.InterruptItem()])
        log_debug(f"Session {self.session.id} interrupted", style="yellow")

    async def run_task(self, user_input: str) -> AsyncGenerator[events.Event, None]:
        task_started_at = time.perf_counter()
        yield events.TaskStartEvent(
            session_id=self.session.id,
            sub_agent_state=self.session.sub_agent_state,
        )

        self.session.append_history([model.UserMessageItem(content=user_input)])

        metadata_merge_state = _MetadataMergeState(
            accumulated=model.ResponseMetadataItem(model_name=self.get_llm_client().model_name)
        )
        last_assistant_message: events.AssistantMessageEvent | None = None

        while True:
            # Each outer loop is a new turn. Process reminders at the start of each turn.
            async for event in self.process_reminders():
                yield event

            failed_turn_attempts = 0
            last_turn_error_message: str | None = None
            while failed_turn_attempts <= MAX_FAILED_TURN_RETRIES:
                # The inner loop handles the execution and potential retries of a single turn.
                turn_has_tool_call = False
                turn_failed = False
                last_turn_error_message = None

                def handle_turn_event(turn_event: events.Event) -> events.Event | None:
                    nonlocal turn_has_tool_call, turn_failed, last_assistant_message, last_turn_error_message
                    match turn_event:
                        case events.ToolCallEvent() as tc:
                            turn_has_tool_call = True
                            return tc
                        case events.ToolResultEvent() as tr:
                            return tr
                        case events.AssistantMessageEvent() as am:
                            if am.content.strip() != "":
                                last_assistant_message = am
                            return am
                        case events.ErrorEvent() as err:
                            turn_failed = True
                            last_turn_error_message = err.error_message
                            return None
                        case events.ResponseMetadataEvent() as e:
                            self._merge_turn_metadata(
                                metadata_merge_state,
                                e.metadata,
                            )
                            status = e.metadata.status
                            if status is not None and status != "completed":
                                turn_failed = True
                            return None
                        case _ as other:
                            return other

                turn_generator = self.run_turn()
                turn_timed_out = False

                try:
                    async with asyncio.timeout(FIRST_EVENT_TIMEOUT_S):
                        # Process events until the first meaningful one, with a timeout.
                        # A "meaningful" event is any event other than TurnStartEvent.
                        async for turn_event in turn_generator:
                            event_to_yield = handle_turn_event(turn_event)
                            if event_to_yield is not None:
                                yield event_to_yield

                            # After yielding, check if it was a meaningful event to break the timeout context
                            if not isinstance(turn_event, events.TurnStartEvent):
                                break
                except (TimeoutError, asyncio.TimeoutError):
                    turn_timed_out = True
                    turn_failed = True
                    log_debug("Turn timed out before first meaningful event, retrying", style="red")
                    # Ensure pending calls are cleared on timeout
                    self.turn_inflight_tool_calls.clear()
                    try:
                        await turn_generator.aclose()
                    except Exception:
                        pass  # Suppress errors on closing the generator

                # If the turn hasn't timed out, continue processing the rest of the events.
                if not turn_timed_out:
                    async for turn_event in turn_generator:
                        event_to_yield = handle_turn_event(turn_event)
                        if event_to_yield is not None:
                            yield event_to_yield

                if not turn_failed:
                    # If the turn succeeded, break the inner retry loop.
                    break

                # If the turn failed, increment the attempt counter and the inner loop will continue.
                failed_turn_attempts += 1
                if failed_turn_attempts > MAX_FAILED_TURN_RETRIES:
                    # Retry budget exhausted; let the loop terminate and emit final error below
                    continue

                retry_delay = self._retry_delay_seconds(failed_turn_attempts)
                if turn_timed_out:
                    error_message = (
                        f"Turn timed out after {FIRST_EVENT_TIMEOUT_S} seconds. "
                        f"Retrying {failed_turn_attempts}/{MAX_FAILED_TURN_RETRIES} in {retry_delay:.1f}s"
                    )
                else:
                    error_message = f"Retrying {failed_turn_attempts}/{MAX_FAILED_TURN_RETRIES} in {retry_delay:.1f}s"

                combined_error_message = error_message
                if last_turn_error_message:
                    combined_error_message = f"{error_message} · {last_turn_error_message}"
                yield events.ErrorEvent(error_message=combined_error_message)
                await asyncio.sleep(retry_delay)
            else:
                # This 'else' belongs to the 'while' loop. It runs if the loop completes without a 'break'.
                # This means all retries have been exhausted and failed.
                log_debug(
                    "Maximum consecutive failed turns reached, aborting task",
                    style="red",
                )
                final_error_message = f"Turn failed after {MAX_FAILED_TURN_RETRIES} retries."
                if last_turn_error_message:
                    final_error_message = f"{last_turn_error_message}\n{final_error_message}"
                yield events.ErrorEvent(error_message=final_error_message)
                return  # Exit the entire run_task method

            if not turn_has_tool_call:
                break

        accumulated_metadata = metadata_merge_state.accumulated

        if accumulated_metadata.usage is not None:
            if metadata_merge_state.throughput_tracked_tokens > 0:
                accumulated_metadata.usage.throughput_tps = (
                    metadata_merge_state.throughput_weighted_sum / metadata_merge_state.throughput_tracked_tokens
                )
            else:
                accumulated_metadata.usage.throughput_tps = None

        accumulated_metadata.task_duration_s = time.perf_counter() - task_started_at

        yield events.ResponseMetadataEvent(metadata=accumulated_metadata, session_id=self.session.id)
        self.session.append_history([accumulated_metadata])
        yield events.TaskFinishEvent(
            session_id=self.session.id,
            task_result=last_assistant_message.content if last_assistant_message else "",
        )

    def _merge_turn_metadata(
        self,
        state: _MetadataMergeState,
        turn_metadata: model.ResponseMetadataItem,
    ) -> None:
        accumulated_metadata = state.accumulated
        usage = turn_metadata.usage
        if usage is not None:
            if accumulated_metadata.usage is None:
                accumulated_metadata.usage = model.Usage()
            accumulated_usage = accumulated_metadata.usage
            accumulated_usage.input_tokens += usage.input_tokens
            accumulated_usage.cached_tokens += usage.cached_tokens
            accumulated_usage.reasoning_tokens += usage.reasoning_tokens
            accumulated_usage.output_tokens += usage.output_tokens
            accumulated_usage.total_tokens += usage.total_tokens
            if usage.context_usage_percent is not None:
                accumulated_usage.context_usage_percent = usage.context_usage_percent

            if usage.first_token_latency_ms is not None:
                if accumulated_usage.first_token_latency_ms is None:
                    accumulated_usage.first_token_latency_ms = usage.first_token_latency_ms
                else:
                    accumulated_usage.first_token_latency_ms = min(
                        accumulated_usage.first_token_latency_ms,
                        usage.first_token_latency_ms,
                    )

            if usage.throughput_tps is not None:
                current_output = usage.output_tokens
                if current_output > 0:
                    state.throughput_weighted_sum += usage.throughput_tps * current_output
                    state.throughput_tracked_tokens += current_output

        if turn_metadata.provider is not None:
            accumulated_metadata.provider = turn_metadata.provider
        if turn_metadata.model_name:
            accumulated_metadata.model_name = turn_metadata.model_name
        if turn_metadata.response_id:
            accumulated_metadata.response_id = turn_metadata.response_id
        if turn_metadata.status is not None:
            accumulated_metadata.status = turn_metadata.status
        if turn_metadata.error_reason is not None:
            accumulated_metadata.error_reason = turn_metadata.error_reason

    async def replay_history(self) -> AsyncGenerator[events.Event, None]:
        """Yield UI events reconstructed from saved conversation history."""

        if len(self.session.conversation_history) == 0:
            return

        yield events.ReplayHistoryEvent(
            events=list(self.session.get_history_item()), updated_at=self.session.updated_at, session_id=self.session.id
        )

    async def run_turn(self) -> AsyncGenerator[events.Event, None]:
        profile = self._require_profile()

        yield events.TurnStartEvent(
            session_id=self.session.id,
        )
        # Clear pending map for new turn
        self.turn_inflight_tool_calls.clear()
        # TODO: If LLM API error occurred, we will discard (not append to history) and retry
        turn_reasoning_items: list[model.ReasoningTextItem | model.ReasoningEncryptedItem] = []
        turn_assistant_message: model.AssistantMessageItem | None = None
        turn_tool_calls: list[model.ToolCallItem] = []
        current_response_id: str | None = None
        response_failed = False

        async for response_item in profile.llm_client.call(
            llm_parameter.LLMCallParameter(
                input=self.session.conversation_history,
                system=profile.system_prompt,
                tools=profile.tools,
                store=False,
                session_id=self.session.id,
            )
        ):
            log_debug(
                f"📁 response [{response_item.__class__.__name__}]",
                response_item.model_dump_json(),
                style="green",
            )
            match response_item:
                case model.StartItem() as item:
                    current_response_id = item.response_id
                case model.ReasoningTextItem() as item:
                    turn_reasoning_items.append(item)
                    yield events.ThinkingEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.ReasoningEncryptedItem() as item:
                    turn_reasoning_items.append(item)
                case model.AssistantMessageDelta() as item:
                    yield events.AssistantMessageDeltaEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.AssistantMessageItem() as item:
                    turn_assistant_message = item
                    yield events.AssistantMessageEvent(
                        content=item.content or "",
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.ResponseMetadataItem() as item:
                    yield events.ResponseMetadataEvent(
                        session_id=self.session.id,
                        metadata=item,
                    )
                case model.StreamErrorItem() as item:
                    response_failed = True
                    log_debug("📁 response [StreamError]", item.error, style="red")
                    yield events.ErrorEvent(error_message=item.error)
                case model.ToolCallItem() as item:
                    turn_tool_calls.append(item)
                case _:
                    pass
        if not response_failed:
            if turn_reasoning_items:
                self.session.append_history(turn_reasoning_items)
            if turn_assistant_message:
                self.session.append_history([turn_assistant_message])
            if turn_tool_calls:
                self.session.append_history(turn_tool_calls)
                # Track tool calls for cancellation handling
                for item in turn_tool_calls:
                    self.turn_inflight_tool_calls[item.call_id] = UnfinishedToolCallItem(
                        tool_call_item=item, status="pending"
                    )
        if current_response_id is not None and not response_failed:
            self.session.last_response_id = current_response_id
        if response_failed:
            # Clear any pending tool calls when the response failed before execution
            self.turn_inflight_tool_calls.clear()
        if turn_tool_calls and not response_failed:
            regular_tool_calls, sub_agent_tool_calls = self._partition_tool_calls(turn_tool_calls)

            for tool_call in regular_tool_calls:
                async for tool_event in self._execute_tool_call(tool_call):
                    yield tool_event

            if sub_agent_tool_calls:
                async for tool_event in self._execute_sub_agent_calls(sub_agent_tool_calls):
                    yield tool_event
        yield events.TurnEndEvent(session_id=self.session.id)

    async def process_reminders(self) -> AsyncGenerator[events.DeveloperMessageEvent, None]:
        reminders = self._require_profile().reminders
        if not reminders:
            return
        for reminder in reminders:
            item = await reminder(self.session)
            if item is not None:
                self.session.append_history([item])
                yield events.DeveloperMessageEvent(session_id=self.session.id, item=item)

    def _retry_delay_seconds(self, attempt: int) -> float:
        capped_attempt = max(1, attempt)
        delay = INITIAL_RETRY_DELAY_S * (2 ** (capped_attempt - 1))
        return min(delay, MAX_RETRY_DELAY_S)

    def set_model_profile(self, profile: AgentProfile) -> None:
        """Apply a fully constructed profile to the agent."""

        self.profile = profile
        # Keep shared client registry in sync for main-agent switches
        if profile.role.name == "main":
            self.llm_clients.main = profile.llm_client
        self.session.model_name = profile.llm_client.model_name

    def build_model_profile(
        self,
        llm_client: LLMClientABC,
        agent_role: AgentRole | None = None,
    ) -> AgentProfile:
        if agent_role is None:
            agent_role = AgentRole.main()
        return self.model_profile_provider.build_profile(llm_client, agent_role)

    def get_llm_client(self) -> LLMClientABC:
        return self._require_profile().llm_client

    def _require_profile(self) -> AgentProfile:
        if self.profile is None:
            raise RuntimeError("Agent profile is not initialized")
        return self.profile

    def _partition_tool_calls(
        self, tool_calls: list[model.ToolCallItem]
    ) -> tuple[list[model.ToolCallItem], list[model.ToolCallItem]]:
        regular_tool_calls: list[model.ToolCallItem] = []
        sub_agent_tool_calls: list[model.ToolCallItem] = []
        for tool_call in tool_calls:
            if is_sub_agent_tool(tool_call.name):
                sub_agent_tool_calls.append(tool_call)
            else:
                regular_tool_calls.append(tool_call)
        return regular_tool_calls, sub_agent_tool_calls

    def _build_tool_call_event(self, tool_call: model.ToolCallItem) -> events.ToolCallEvent:
        return events.ToolCallEvent(
            tool_call_id=tool_call.call_id,
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
            response_id=tool_call.response_id,
            session_id=self.session.id,
        )

    async def _execute_tool_call(self, tool_call: model.ToolCallItem) -> AsyncGenerator[events.Event, None]:
        yield self._build_tool_call_event(tool_call)

        for tool_event in await self._run_tool_call(tool_call):
            yield tool_event

    async def _execute_sub_agent_calls(
        self, tool_calls: list[model.ToolCallItem]
    ) -> AsyncGenerator[events.Event, None]:
        execution_tasks: list[asyncio.Task[list[events.Event]]] = []
        for tool_call in tool_calls:
            yield self._build_tool_call_event(tool_call)
            execution_tasks.append(asyncio.create_task(self._run_tool_call(tool_call)))

        for task in asyncio.as_completed(execution_tasks):
            for tool_event in await task:
                yield tool_event

    async def _run_tool_call(self, tool_call: model.ToolCallItem) -> list[events.Event]:
        session_token = current_session_var.set(self.session)
        try:
            self.turn_inflight_tool_calls[tool_call.call_id].status = "in_progress"
            tool_result: model.ToolResultItem = await run_tool(tool_call)
        finally:
            current_session_var.reset(session_token)

        self.session.append_history([tool_result])
        result_event = events.ToolResultEvent(
            tool_call_id=tool_call.call_id,
            tool_name=tool_call.name,
            result=tool_result.output or "",
            ui_extra=tool_result.ui_extra,
            response_id=tool_call.response_id,
            session_id=self.session.id,
            status=tool_result.status,
        )

        self.turn_inflight_tool_calls.pop(tool_call.call_id, None)

        extra_events: list[events.Event] = []
        if tool_call.name in (tools.TODO_WRITE, tools.UPDATE_PLAN):
            extra_events.append(
                events.TodoChangeEvent(
                    session_id=self.session.id,
                    todos=self.session.todos,
                )
            )

        return [result_event, *extra_events]
