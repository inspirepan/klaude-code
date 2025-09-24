from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass
from typing import Literal

from codex_mini.core.prompt import get_system_prompt
from codex_mini.core.reminders import Reminder
from codex_mini.core.tool.tool_context import current_exit_plan_mode_callback, current_session_var
from codex_mini.core.tool.tool_registry import run_tool
from codex_mini.llm.client import LLMClientABC
from codex_mini.protocol import events, llm_parameter, model, tools
from codex_mini.session import Session
from codex_mini.trace import log_debug

# Constant for cancellation message
CANCEL_OUTPUT = "[Request interrupted by user for tool use]"


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

        while True:
            async for event in self.process_reminders():
                yield event
            turn_has_tool_call = False
            async for turn_event in self.run_turn():
                match turn_event:
                    case events.ToolCallEvent() as tc:
                        turn_has_tool_call = True
                        yield tc
                    case events.ToolResultEvent() as tr:
                        yield tr
                    case events.AssistantMessageEvent() as am:
                        if am.content.strip() != "":
                            last_assistant_message = am
                        yield am
                    case events.ResponseMetadataEvent() as e:
                        self._merge_turn_metadata(
                            metadata_merge_state,
                            e.metadata,
                        )
                    case _ as metadata:
                        yield metadata
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

    async def replay_history(self) -> AsyncGenerator[events.Event, None]:
        """Yield UI events reconstructed from saved conversation history."""

        if len(self.session.conversation_history) == 0:
            return

        yield events.ReplayHistoryEvent(
            events=self.session.get_history_item(), updated_at=self.session.updated_at, session_id=self.session.id
        )

    async def run_turn(self) -> AsyncGenerator[events.Event, None]:
        yield events.TurnStartEvent(
            session_id=self.session.id,
        )
        # Clear pending map for new turn
        self.turn_inflight_tool_calls.clear()
        # TODO: If LLM API error occurred, we will discard (not append to history) and retry
        turn_reasoning_item: model.ReasoningItem | None = None
        turn_assistant_message: model.AssistantMessageItem | None = None
        turn_tool_calls: list[model.ToolCallItem] = []
        current_response_id: str | None = None
        store_at_remote = False  # This is the 'store' parameter of OpenAI Responses API for storing history at OpenAI, currently always False

        async for response_item in self.get_llm_client().call(
            llm_parameter.LLMCallParameter(
                input=self.session.conversation_history,
                system=self.session.system_prompt,
                tools=self.tools,
                previous_response_id=self.session.last_response_id if store_at_remote else None,
                store=store_at_remote,
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
                    turn_reasoning_item = item
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
                case model.ToolCallItem() as item:
                    turn_tool_calls.append(item)
                case _:
                    pass
        if not store_at_remote:
            if turn_reasoning_item:
                self.session.append_history([turn_reasoning_item])
            if turn_assistant_message:
                self.session.append_history([turn_assistant_message])
            if turn_tool_calls:
                self.session.append_history(turn_tool_calls)
                # Track tool calls for cancellation handling
                for item in turn_tool_calls:
                    self.turn_inflight_tool_calls[item.call_id] = UnfinishedToolCallItem(
                        tool_call_item=item, status="pending"
                    )
        if current_response_id is not None:
            self.session.last_response_id = current_response_id
        if turn_tool_calls:
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
                if tool_call.name == tools.TODO_WRITE:
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

    def sync_system_prompt(self, sub_agent_type: tools.SubAgentType | None = None) -> None:
        if self.vanilla:
            self.session.system_prompt = "You're a help assistant"
            return

        if sub_agent_type == tools.SubAgentType.TASK:
            self.session.system_prompt = get_system_prompt(self.llm_clients.main.model_name, "task")
        elif sub_agent_type == tools.SubAgentType.ORACLE:
            self.session.system_prompt = get_system_prompt(self.llm_clients.main.model_name, "oracle")
        else:
            self.session.system_prompt = get_system_prompt(self.llm_clients.main.model_name, "main")

    def set_llm_client(self, llm_client: LLMClientABC) -> None:
        if self.session.is_in_plan_mode:
            self.llm_clients.plan = llm_client
        else:
            self.llm_clients.main = llm_client
        self.session.model_name = llm_client.model_name

    def get_llm_client(self) -> LLMClientABC:
        if self.session.is_in_plan_mode and self.llm_clients.plan:
            return self.llm_clients.plan
        else:
            return self.llm_clients.main

    def exit_plan_mode(self) -> str:
        """Exit plan mode and switch back to executor LLM client, return a message for tool result"""
        self.session.is_in_plan_mode = False
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
        if self.llm_clients.plan is not None:
            self.sync_system_prompt()
            return self.llm_clients.plan.model_name
        return self.llm_clients.main.model_name
