from collections.abc import AsyncGenerator, Awaitable, Callable

from codex_mini.core.tool.tool_context import current_session_var
from codex_mini.core.tool.tool_registry import run_tool
from codex_mini.llm.client import LLMClientABC
from codex_mini.protocol import events, llm_parameter, model, tools
from codex_mini.session import Session
from codex_mini.trace import log_debug


class Agent:
    def __init__(
        self,
        llm_client: LLMClientABC,
        session: Session,
        tools: list[llm_parameter.ToolSchema] | None = None,
        debug_mode: bool = False,
        reminders: list[Callable[[Session], Awaitable[model.DeveloperMessageItem | None]]] = [],
    ):
        self.session: Session = session
        self.llm_client: LLMClientABC = llm_client
        self.tools: list[llm_parameter.ToolSchema] | None = tools
        self.debug_mode: bool = debug_mode
        self.reminders: list[Callable[[Session], Awaitable[model.DeveloperMessageItem | None]]] = reminders

    def cancel(self) -> None:
        """Handle agent cancellation and persist an interrupt marker.

        Appends a `model.InterruptItem` into the session history so that
        interruptions are reflected in persisted conversation logs.
        """
        # Record an interrupt marker in the session history
        self.session.append_history([model.InterruptItem()])
        if self.debug_mode:
            log_debug(f"Session {self.session.id} interrupted", style="yellow")

    async def run_task(self, user_input: str) -> AsyncGenerator[events.Event, None]:
        yield events.TaskStartEvent(session_id=self.session.id)

        self.session.append_history([model.UserMessageItem(content=user_input)])

        accumulated_metadata: model.ResponseMetadataItem = model.ResponseMetadataItem(model_name="")

        while True:
            async for event in self.process_reminders():
                yield event
            turn_has_tool_call = False
            async for turn_event in self.run_turn():
                match turn_event:
                    case events.ToolCallEvent() as metadata:
                        turn_has_tool_call = True
                        yield metadata
                    case events.ResponseMetadataEvent() as e:
                        metadata = e.metadata
                        if metadata.usage is not None:
                            if accumulated_metadata.usage is None:
                                accumulated_metadata.usage = model.Usage()
                            accumulated_metadata.usage.input_tokens += metadata.usage.input_tokens
                            accumulated_metadata.usage.cached_tokens += metadata.usage.cached_tokens
                            accumulated_metadata.usage.reasoning_tokens += metadata.usage.reasoning_tokens
                            accumulated_metadata.usage.output_tokens += metadata.usage.output_tokens
                            accumulated_metadata.usage.total_tokens += metadata.usage.total_tokens
                        if metadata.provider is not None:
                            accumulated_metadata.provider = metadata.provider
                        if metadata.model_name:
                            accumulated_metadata.model_name = metadata.model_name
                        if metadata.response_id:
                            accumulated_metadata.response_id = metadata.response_id
                    case _ as metadata:
                        yield metadata
            if not turn_has_tool_call:
                break

        yield events.ResponseMetadataEvent(metadata=accumulated_metadata, session_id=self.session.id)
        self.session.append_history([accumulated_metadata])
        yield events.TaskFinishEvent(session_id=self.session.id)

    async def replay_history(self) -> AsyncGenerator[events.Event, None]:
        """Yield UI events reconstructed from saved conversation history."""

        if len(self.session.conversation_history) == 0:
            return

        replay_events: list[events.HistoryItemEvent] = []

        for it in self.session.conversation_history:
            match it:
                case model.AssistantMessageItem() as am:
                    content = am.content or ""
                    replay_events.append(
                        events.AssistantMessageEvent(
                            content=content,
                            response_id=am.response_id,
                            session_id=self.session.id,
                            annotations=am.annotations,
                        )
                    )
                case model.ToolCallItem() as tc:
                    replay_events.append(
                        events.ToolCallEvent(
                            tool_call_id=tc.call_id,
                            tool_name=tc.name,
                            arguments=tc.arguments,
                            response_id=tc.response_id,
                            session_id=self.session.id,
                        )
                    )
                case model.ToolResultItem() as tr:
                    replay_events.append(
                        events.ToolResultEvent(
                            tool_call_id=tr.call_id,
                            tool_name=str(tr.tool_name),
                            result=tr.output or "",
                            ui_extra=tr.ui_extra,
                            session_id=self.session.id,
                            status=tr.status,
                        )
                    )
                case model.UserMessageItem() as um:
                    replay_events.append(
                        events.UserMessageEvent(
                            content=um.content or "",
                            session_id=self.session.id,
                        )
                    )
                case model.ReasoningItem() as ri:
                    replay_events.append(
                        events.ThinkingEvent(
                            content=ri.content or ("\n".join(ri.summary or [])),
                            session_id=self.session.id,
                        )
                    )
                case model.ResponseMetadataItem() as mt:
                    replay_events.append(
                        events.ResponseMetadataEvent(
                            session_id=self.session.id,
                            metadata=mt,
                        )
                    )
                case model.InterruptItem():
                    replay_events.append(
                        events.InterruptEvent(
                            session_id=self.session.id,
                        )
                    )
                case model.DeveloperMessageItem() as dm:
                    replay_events.append(
                        events.DeveloperMessageEvent(
                            session_id=self.session.id,
                            item=dm,
                        )
                    )
                case _:
                    continue

        yield events.ReplayHistoryEvent(events=replay_events, updated_at=self.session.updated_at)

    async def run_turn(self) -> AsyncGenerator[events.Event, None]:
        # TODO: If LLM API error occurred, we will discard (not append to history) and retry
        turn_reasoning_item: model.ReasoningItem | None = None
        turn_assistant_message: model.AssistantMessageItem | None = None
        turn_tool_calls: list[model.ToolCallItem] = []
        current_response_id: str | None = None
        store_at_remote = False  # This is the 'store' parameter of OpenAI Responses API for storing history at OpenAI, currently always False

        async for response_item in self.llm_client.call(
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
                case model.ThinkingTextItem() as item:
                    yield events.ThinkingEvent(
                        content=item.thinking,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.ReasoningItem() as item:
                    turn_reasoning_item = item
                case model.AssistantMessageDelta() as item:
                    if item.content.strip() == "":
                        continue
                    yield events.AssistantMessageDeltaEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.AssistantMessageItem() as item:
                    if not item.content or item.content.strip() == "":
                        continue
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
                token = current_session_var.set(self.session)
                try:
                    tool_result: model.ToolResultItem = await run_tool(tool_call)
                finally:
                    current_session_var.reset(token)
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
                if tool_call.name == tools.TODO_WRITE_TOOL_NAME:
                    yield events.TodoChangeEvent(
                        session_id=self.session.id,
                        todos=self.session.todos,
                    )

    async def process_reminders(self) -> AsyncGenerator[events.DeveloperMessageEvent, None]:
        for reminder in self.reminders:
            item = await reminder(self.session)
            if item is not None:
                self.session.append_history([item])
                yield events.DeveloperMessageEvent(session_id=self.session.id, item=item)
