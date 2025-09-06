from collections.abc import AsyncGenerator
from pathlib import Path

from codex_mini.core.tool.tool_context import current_session_var
from codex_mini.core.tool.tool_registry import run_tool
from codex_mini.llm.client import LLMClientABC
from codex_mini.protocol import events, llm_parameter, model
from codex_mini.session import Session
from codex_mini.trace import log_debug


class Agent:
    def __init__(
        self,
        llm_client: LLMClientABC,
        session_id: str | None = None,
        system_prompt: str | None = None,
        tools: list[llm_parameter.ToolSchema] | None = None,
        debug_mode: bool = False,
    ):
        work_dir: Path = Path.cwd()
        self.session: Session = (
            Session(work_dir=work_dir, system_prompt=system_prompt) if session_id is None else Session.load(session_id)
        )
        self.llm_client: LLMClientABC = llm_client
        self.tools: list[llm_parameter.ToolSchema] | None = tools
        self.debug_mode: bool = debug_mode

    async def run_task(self, user_input: str) -> AsyncGenerator[events.Event, None]:
        yield events.TaskStartEvent(session_id=self.session.id)

        self.session.append_history([model.UserMessageItem(content=user_input)])

        accumulated_metadata: events.ResponseMetadataEvent = events.ResponseMetadataEvent(
            model_name="",
            session_id=self.session.id,
        )

        while True:
            turn_has_tool_call = False
            async for turn_event in self.run_turn():
                match turn_event:
                    case events.ToolCallEvent() as event:
                        turn_has_tool_call = True
                        yield event
                    case events.ResponseMetadataEvent() as event:
                        if event.usage is not None:
                            if accumulated_metadata.usage is None:
                                accumulated_metadata.usage = model.Usage()
                            accumulated_metadata.usage.input_tokens += event.usage.input_tokens
                            accumulated_metadata.usage.cached_tokens += event.usage.cached_tokens
                            accumulated_metadata.usage.reasoning_tokens += event.usage.reasoning_tokens
                            accumulated_metadata.usage.output_tokens += event.usage.output_tokens
                            accumulated_metadata.usage.total_tokens += event.usage.total_tokens
                        if event.provider is not None:
                            accumulated_metadata.provider = event.provider
                        if event.model_name:
                            accumulated_metadata.model_name = event.model_name
                        if event.response_id:
                            accumulated_metadata.response_id = event.response_id
                    case _ as event:
                        yield event
            if not turn_has_tool_call:
                break

        yield accumulated_metadata
        yield events.TaskFinishEvent(session_id=self.session.id)

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
                        response_id=item.response_id,
                        session_id=self.session.id,
                        usage=item.usage,
                        model_name=item.model_name,
                        provider=item.provider,
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
