from collections.abc import AsyncGenerator
from pathlib import Path

from codex_mini.core.prompt.system import get_system_prompt
from codex_mini.core.tool.tool_registry import run_tool
from codex_mini.llm.client import LLMClient
from codex_mini.protocol import events
from codex_mini.protocol import llm_parameter
from codex_mini.protocol import model
from codex_mini.session import Session


class Agent:
    def __init__(
        self,
        llm_client: LLMClient,
        session_id: str | None = None,
        tools: list[llm_parameter.ToolSchema] | None = None,
    ):
        work_dir: Path = Path.cwd()
        self.session: Session = (
            Session(work_dir=work_dir, system_prompt=get_system_prompt())
            if session_id is None
            else Session.load(session_id)
        )
        self.llm_client: LLMClient = llm_client
        self.tools: list[llm_parameter.ToolSchema] | None = tools

    async def run_task(self, user_input: str) -> AsyncGenerator[events.Event, None]:
        yield events.TaskStartEvent(session_id=self.session.id)

        self.session.append_history([model.UserMessage(content=user_input)])

        task_usage: model.Usage = model.Usage()
        model_name = ""

        while True:
            turn_has_tool_call = False
            async for turn_event in self.run_turn():
                match turn_event:
                    case events.ToolCallEvent() as event:
                        turn_has_tool_call = True
                        yield event
                    case events.ResponseMetadataEvent() as event:
                        if event.usage is not None:
                            task_usage.input_tokens += event.usage.input_tokens
                            task_usage.cached_tokens += event.usage.cached_tokens
                            task_usage.reasoning_tokens += event.usage.reasoning_tokens
                            task_usage.output_tokens += event.usage.output_tokens
                            task_usage.total_tokens += event.usage.total_tokens
                        model_name = event.model_name
                    case _ as event:
                        yield event
            if not turn_has_tool_call:
                break
        yield events.ResponseMetadataEvent(
            usage=task_usage,
            session_id=self.session.id,
            response_id=self.session.last_response_id,
            model_name=model_name,
        )
        yield events.TaskFinishEvent(session_id=self.session.id)

    async def run_turn(self) -> AsyncGenerator[events.Event, None]:
        # If LLM API error occurred, we will discard (not append to history) and retry
        turn_reasoning_items: model.ReasoningItem | None = None
        turn_assistant_message: model.AssistantMessage | None = None
        turn_tool_calls: list[model.ToolCallItem] = []
        current_response_id: str | None = None
        store_at_remote = False  # This is the 'store' parameter of OpenAI Responses API for storing history at OpenAI, currently always False

        async for response_item in self.llm_client.Call(
            llm_parameter.LLMCallParameter(
                input=self.session.conversation_history,
                system=self.session.system_prompt,
                tools=self.tools,
                previous_response_id=self.session.last_response_id
                if store_at_remote
                else None,
                store=store_at_remote,
            )
        ):
            match response_item:
                case model.StartItem() as item:
                    current_response_id = item.response_id
                case model.ThinkingTextDelta() as item:
                    yield events.ThinkingDeltaEvent(
                        content=item.thinking,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.ThinkingTextDone() as item:
                    yield events.ThinkingEvent(
                        content=item.thinking,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.ReasoningItem() as item:
                    turn_reasoning_items = item
                case model.AssistantMessageTextDelta() as item:
                    yield events.AssistantMessageDeltaEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case model.AssistantMessage() as item:
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
                    )
                case model.ToolCallItem() as item:
                    turn_tool_calls.append(item)
                case _:
                    pass
        if not store_at_remote:
            if turn_reasoning_items:
                self.session.append_history([turn_reasoning_items])
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
                tool_result: model.ToolMessage = await run_tool(tool_call)
                self.session.append_history([tool_result])
                yield events.ToolCallResultEvent(
                    tool_call_id=tool_call.call_id,
                    tool_name=tool_call.name,
                    result=tool_result.content or "",
                    ui_extra=tool_result.ui_extra,
                    response_id=tool_call.response_id,
                    session_id=self.session.id,
                    status=tool_result.status,
                )
