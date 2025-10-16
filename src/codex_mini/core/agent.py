import asyncio
import time
from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass
from typing import Literal

from codex_mini.core.prompt import get_system_prompt
from codex_mini.core.reminders import Reminder, get_main_agent_reminders, get_sub_agent_reminders
from codex_mini.core.tool.tool_context import current_exit_plan_mode_callback, current_session_var
from codex_mini.core.tool.tool_registry import get_main_agent_tools, get_sub_agent_tools, run_tool
from codex_mini.llm.client import LLMClientABC
from codex_mini.protocol import events, llm_parameter, model, tools
from codex_mini.session import Session
from codex_mini.trace import log_debug

# Constant for cancellation message
CANCEL_OUTPUT = "[Request interrupted by user for tool use]"
FIRST_EVENT_TIMEOUT_S = 60.0
MAX_FAILED_TURN_RETRIES = 10
INITIAL_RETRY_DELAY_S = 1.0
MAX_RETRY_DELAY_S = 30.0


@dataclass
class AgentLLMClients:
    main: LLMClientABC
    plan: LLMClientABC | None = None
    fast: LLMClientABC | None = None  # Not used for now
    task: LLMClientABC | None = None
    oracle: LLMClientABC | None = None

    def get_sub_agent_client(self, sub_agent_type: tools.SubAgentType) -> LLMClientABC:
        if sub_agent_type == tools.SubAgentType.TASK:
            return self.task or self.main
        elif sub_agent_type == tools.SubAgentType.ORACLE:
            return self.oracle or self.main
        else:
            return self.main


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


class Agent:
    def __init__(
        self,
        llm_clients: AgentLLMClients,
        session: Session,
        tools: list[llm_parameter.ToolSchema] | None = None,
        debug_mode: bool = False,
        reminders: list[Reminder] | None = None,
        vanilla: bool = False,
    ):
        self.session: Session = session
        self.tools: list[llm_parameter.ToolSchema] | None = tools
        self.debug_mode: bool = debug_mode
        self.reminders: list[Reminder] | None = reminders
        self.llm_clients = llm_clients
        self.vanilla = vanilla
        # Track tool calls that are pending or in-progress within the current turn
        # Keyed by tool_call_id
        self.turn_inflight_tool_calls: dict[str, UnfinishedToolCallItem] = {}
        self.session.model_name = llm_clients.main.model_name
        # Ensure runtime configuration matches the active model on initialization
        self.refresh_model_profile()

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
        if self.debug_mode:
            log_debug(f"Session {self.session.id} interrupted", style="yellow")

    async def run_task(self, user_input: str) -> AsyncGenerator[events.Event, None]:
        task_started_at = time.perf_counter()
        yield events.TaskStartEvent(
            session_id=self.session.id,
            is_sub_agent=not self.session.is_root_session,
            sub_agent_type=self.session.sub_agent_type,
        )

        self.session.append_history([model.UserMessageItem(content=user_input)])

        metadata_merge_state = _MetadataMergeState(
            accumulated=model.ResponseMetadataItem(model_name=self.get_llm_client().model_name)
        )
        last_assistant_message: events.AssistantMessageEvent | None = None
        turn_count = 0

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
                    if self.debug_mode:
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
                if self.debug_mode:
                    log_debug(
                        "Maximum consecutive failed turns reached, aborting task",
                        style="red",
                    )
                final_error_message = f"Turn failed after {MAX_FAILED_TURN_RETRIES} retries."
                if last_turn_error_message:
                    final_error_message = f"{last_turn_error_message}\n{final_error_message}"
                yield events.ErrorEvent(error_message=final_error_message)
                return  # Exit the entire run_task method

            turn_count += 1
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
        accumulated_metadata.turn_count = turn_count

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
        yield events.TurnStartEvent(
            session_id=self.session.id,
        )
        # Clear pending map for new turn
        self.turn_inflight_tool_calls.clear()
        # TODO: If LLM API error occurred, we will discard (not append to history) and retry
        turn_reasoning_items: list[model.ReasoningItem] = []
        turn_assistant_message: model.AssistantMessageItem | None = None
        turn_tool_calls: list[model.ToolCallItem] = []
        current_response_id: str | None = None
        store_at_remote = False  # This is the 'store' parameter of OpenAI Responses API for storing history at OpenAI, currently always False
        response_failed = False

        async for response_item in self.get_llm_client().call(
            llm_parameter.LLMCallParameter(
                input=self.session.conversation_history,
                system=self.session.system_prompt,
                tools=self.tools,
                previous_response_id=self.session.last_response_id if store_at_remote else None,
                store=store_at_remote,
                session_id=self.session.id,
            )
        ):
            if self.debug_mode:
                log_debug(
                    f"◀◀◀ response [{response_item.__class__.__name__}]",
                    response_item.model_dump_json(),
                    style="green",
                )
            match response_item:
                case model.StartItem() as item:
                    current_response_id = item.response_id
                case model.ThinkingTextDelta() as item:
                    yield events.ThinkingDeltaEvent(
                        content=item.thinking,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.ReasoningItem() as item:
                    turn_reasoning_items.append(item)
                    thinking = "\n".join(item.summary) if item.summary else item.content
                    if thinking:
                        yield events.ThinkingEvent(
                            content=thinking,
                            response_id=item.response_id,
                            session_id=self.session.id,
                        )
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
                        annotations=item.annotations,
                    )
                case model.ResponseMetadataItem() as item:
                    yield events.ResponseMetadataEvent(
                        session_id=self.session.id,
                        metadata=item,
                    )
                case model.StreamErrorItem() as item:
                    response_failed = True
                    if self.debug_mode:
                        log_debug("◀◀◀ response [StreamError]", item.error, style="red")
                    yield events.ErrorEvent(error_message=item.error)
                case model.ToolCallItem() as item:
                    turn_tool_calls.append(item)
                case _:
                    pass
        if not store_at_remote and not response_failed:
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
            for tool_call in turn_tool_calls:
                yield events.ToolCallEvent(
                    tool_call_id=tool_call.call_id,
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    response_id=tool_call.response_id,
                    session_id=self.session.id,
                )
                session_token = current_session_var.set(self.session)
                exit_plan_mode_token = current_exit_plan_mode_callback.set(self.exit_plan_mode)
                try:
                    self.turn_inflight_tool_calls[tool_call.call_id].status = "in_progress"
                    tool_result: model.ToolResultItem = await run_tool(tool_call)
                finally:
                    current_session_var.reset(session_token)
                    current_exit_plan_mode_callback.reset(exit_plan_mode_token)
                self.session.append_history([tool_result])
                yield events.ToolResultEvent(
                    tool_call_id=tool_call.call_id,
                    tool_name=tool_call.name,
                    result=tool_result.output or "",
                    ui_extra=tool_result.ui_extra,
                    response_id=tool_call.response_id,
                    session_id=self.session.id,
                    status=tool_result.status,
                )
                if tool_call.name in (tools.TODO_WRITE, tools.UPDATE_PLAN):
                    yield events.TodoChangeEvent(
                        session_id=self.session.id,
                        todos=self.session.todos,
                    )
                # Remove from pending after result is produced
                self.turn_inflight_tool_calls.pop(tool_call.call_id, None)
        yield events.TurnEndEvent(session_id=self.session.id)

    async def process_reminders(self) -> AsyncGenerator[events.DeveloperMessageEvent, None]:
        if self.reminders is None:
            return
        for reminder in self.reminders:
            item = await reminder(self.session)
            if item is not None:
                self.session.append_history([item])
                yield events.DeveloperMessageEvent(session_id=self.session.id, item=item)

    def _retry_delay_seconds(self, attempt: int) -> float:
        capped_attempt = max(1, attempt)
        delay = INITIAL_RETRY_DELAY_S * (2 ** (capped_attempt - 1))
        return min(delay, MAX_RETRY_DELAY_S)

    def refresh_model_profile(self, sub_agent_type: tools.SubAgentType | None = None) -> None:
        """Refresh system prompt, tools, and reminders for the active model."""

        effective_sub_agent_type = sub_agent_type or self.session.sub_agent_type
        active_client = self._resolve_llm_client_for(effective_sub_agent_type)
        active_model_name = active_client.model_name
        self.session.model_name = active_model_name

        if self.vanilla:
            self.session.system_prompt = None
        else:
            if effective_sub_agent_type == tools.SubAgentType.TASK:
                prompt_key = "task"
            elif effective_sub_agent_type == tools.SubAgentType.ORACLE:
                prompt_key = "oracle"
            else:
                prompt_key = "main"
            self.session.system_prompt = get_system_prompt(active_model_name, prompt_key)

        if effective_sub_agent_type == tools.SubAgentType.TASK:
            self.tools = get_sub_agent_tools(active_model_name, tools.SubAgentType.TASK)
            self.reminders = get_sub_agent_reminders(self.vanilla, active_model_name)
            return
        if effective_sub_agent_type == tools.SubAgentType.ORACLE:
            self.tools = get_sub_agent_tools(active_model_name, tools.SubAgentType.ORACLE)
            self.reminders = get_sub_agent_reminders(self.vanilla, active_model_name)
            return

        self.tools = get_main_agent_tools(active_model_name)
        self.reminders = get_main_agent_reminders(self.vanilla, active_model_name)

    def set_llm_client(self, llm_client: LLMClientABC) -> None:
        if self.session.is_in_plan_mode:
            self.llm_clients.plan = llm_client
        else:
            self.llm_clients.main = llm_client
        self.refresh_model_profile()

    def get_llm_client(self) -> LLMClientABC:
        return self._resolve_llm_client_for()

    def _resolve_llm_client_for(self, sub_agent_type: tools.SubAgentType | None = None) -> LLMClientABC:
        effective_sub_agent_type = sub_agent_type or self.session.sub_agent_type

        # Subagent
        if effective_sub_agent_type == tools.SubAgentType.TASK:
            return self.llm_clients.get_sub_agent_client(tools.SubAgentType.TASK)
        if effective_sub_agent_type == tools.SubAgentType.ORACLE:
            return self.llm_clients.get_sub_agent_client(tools.SubAgentType.ORACLE)

        # Plan mode
        if self.session.is_in_plan_mode and self.llm_clients.plan is not None:
            return self.llm_clients.plan

        # Main agent
        return self.llm_clients.main

    def exit_plan_mode(self) -> str:
        """Exit plan mode and switch back to executor LLM client, return a message for tool result"""
        self.session.is_in_plan_mode = False
        self.refresh_model_profile()
        # TODO: If model is switched here, for Claude, the following error may occur
        # because Claude does not allow losing thinking during consecutive assistant and tool_result conversation turns when extended thinking is enabled
        #
        # The solution is to insert a user_message after the tool_message of exit_plan_mode
        # when exiting plan mode. The content can be arbitrary, such as "Continue executing
        # the plan"
        #
        # [BadRequestError] Error code: 400 - {'error': {'message':
        # '-4316: messages.1.content.0.type: Expected `thinking` or `redacted_thinking`,
        # but found `text`. When `thinking` is enabled, a final `assistant` message must
        # start with a thinking block (preceeding the lastmost set of `tool_use` and
        # `tool_result` blocks). We recommend you include thinking blocks from previous
        # turns. To avoid this requirement, disable `thinking`. Please consult our
        # documentation at https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking',
        # 'code': '-4003'}}

        return self.llm_clients.main.model_name

    def enter_plan_mode(self) -> str:
        self.session.is_in_plan_mode = True
        self.refresh_model_profile()
        return self.get_llm_client().model_name
