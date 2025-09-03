from collections.abc import AsyncGenerator
from pathlib import Path

from src.agent.tool.tool_registry import run_tool
from src.llm.client import LLMClient
from src.prompt.system import get_system_prompt
from src.protocal.events import (
    AssistantMessageDeltaEvent,
    AssistantMessageEvent,
    Event,
    ResponseMetadataEvent,
    TaskFinishEvent,
    TaskStartEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCallResultEvent,
)
from src.protocal.llm_parameter import LLMCallParameter, ToolSchema
from src.protocal.model import (
    AssistantMessage,
    AssistantMessageTextDelta,
    ContentPart,
    ReasoningItem,
    ResponseMetadataItem,
    StartItem,
    ThinkingTextDelta,
    ThinkingTextDone,
    ToolCallItem,
    ToolMessage,
    Usage,
    UserMessage,
)
from src.session import Session


class Agent:
    def __init__(
        self,
        llm_client: LLMClient,
        session_id: str | None = None,
        tools: list[ToolSchema] | None = None,
    ):
        work_dir: Path = Path.cwd()
        self.session: Session = (
            Session(work_dir=work_dir, system_prompt=get_system_prompt())
            if session_id is None
            else Session.load(session_id)
        )
        self.llm_client: LLMClient = llm_client
        self.tools: list[ToolSchema] | None = tools

    async def run_task(self, user_input: str) -> AsyncGenerator[Event, None]:
        yield TaskStartEvent(session_id=self.session.id)

        self.session.append_history(
            [UserMessage(content=[ContentPart(text=user_input)])]
        )

        task_usage: Usage = Usage()

        while True:
            turn_has_tool_call = False
            async for turn_event in self.run_turn():
                match turn_event:
                    case ToolCallEvent() as event:
                        turn_has_tool_call = True
                        yield event
                    case ResponseMetadataEvent() as event:
                        if event.usage is not None:
                            task_usage.input_tokens += event.usage.input_tokens
                            task_usage.cached_tokens += event.usage.cached_tokens
                            task_usage.reasoning_tokens += event.usage.reasoning_tokens
                            task_usage.output_tokens += event.usage.output_tokens
                            task_usage.total_tokens += event.usage.total_tokens
                    case _ as event:
                        yield event
            if not turn_has_tool_call:
                break
        yield ResponseMetadataEvent(
            usage=task_usage,
            session_id=self.session.id,
            response_id=self.session.preprevious_response_id,
        )
        yield TaskFinishEvent(session_id=self.session.id)

    async def run_turn(self) -> AsyncGenerator[Event, None]:
        # If LLM API error occurred, we will discard (not append to history) and retry
        turn_reasoning_items: ReasoningItem | None = None
        turn_assistant_message: AssistantMessage | None = None
        turn_tool_calls: list[ToolCallItem] = []
        current_response_id: str | None = None
        store_at_remote = False  # This is the 'store' parameter of OpenAI Responses API for storing history at OpenAI

        async for response_item in self.llm_client.Call(
            LLMCallParameter(
                input=self.session.conversation_history,
                system=self.session.system_prompt,
                tools=self.tools,
                previous_response_id=self.session.preprevious_response_id
                if store_at_remote
                else None,
                store=store_at_remote,
            )
        ):
            match response_item:
                case StartItem() as item:
                    current_response_id = item.response_id
                case ThinkingTextDelta() as item:
                    yield ThinkingDeltaEvent(
                        content=item.thinking,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case ThinkingTextDone() as item:
                    yield ThinkingEvent(
                        content=item.thinking,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case ReasoningItem() as item:
                    turn_reasoning_items = item
                case AssistantMessageTextDelta() as item:
                    yield AssistantMessageDeltaEvent(
                        content=item.content,
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case AssistantMessage() as item:
                    turn_assistant_message = item
                    yield AssistantMessageEvent(
                        content="\n".join(
                            [str(content_item.text) for content_item in item.content]
                        ),
                        response_id=item.response_id,
                        session_id=self.session.id,
                    )
                case ResponseMetadataItem() as item:
                    yield ResponseMetadataEvent(
                        response_id=item.response_id,
                        session_id=self.session.id,
                        usage=item.usage,
                    )
                case ToolCallItem() as item:
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
            self.session.preprevious_response_id = current_response_id
        if turn_tool_calls:
            for tool_call in turn_tool_calls:
                yield ToolCallEvent(
                    tool_call_id=tool_call.call_id,
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    response_id=tool_call.response_id,
                    session_id=self.session.id,
                )
                tool_result: ToolMessage = await run_tool(tool_call)
                self.session.append_history([tool_result])
                yield ToolCallResultEvent(
                    tool_call_id=tool_call.call_id,
                    tool_name=tool_call.name,
                    result="\n".join(
                        [str(content_item.text) for content_item in tool_result.content]
                    ),
                    ui_extra=tool_result.ui_extra,
                    response_id=tool_call.response_id,
                    session_id=self.session.id,
                    status=tool_result.status,
                )
