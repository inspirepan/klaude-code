from collections.abc import AsyncGenerator
from pathlib import Path

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
)
from src.protocal.llm_parameter import LLMCallParameter
from src.protocal.model import (
    AssistantMessage,
    AssistantMessageTextDelta,
    ContentPart,
    ReasoningItem,
    ResponseItem,
    ResponseMetadataItem,
    ThinkingTextDelta,
    ThinkingTextDone,
    ToolCallItem,
    UserMessage,
)
from src.session import Session


class Agent:
    def __init__(self, llm_client: LLMClient, session_id: str | None = None):
        work_dir: Path = Path.cwd()
        self.session: Session = (
            Session(work_dir=work_dir, system_prompt=get_system_prompt())
            if session_id is None
            else Session.load(session_id)
        )
        self.llm_client: LLMClient = llm_client

    async def run_task(self, user_input: str) -> AsyncGenerator[Event, None]:
        yield TaskStartEvent(session_id=self.session.id)

        self.session.append_history(
            [UserMessage(content=[ContentPart(text=user_input)])]
        )
        while True:
            async for response_item in self.run_turn():
                yield response_item
            break
        yield TaskFinishEvent(session_id=self.session.id)

    async def run_turn(self) -> AsyncGenerator[Event, None]:
        # If LLM API error occurred, we will discard (not append to history) and retry
        turn_reasoning_items: ReasoningItem | None = None
        turn_assistant_message: AssistantMessage | None = None
        turn_tool_calls: list[ResponseItem] = []

        async for response_item in self.llm_client.Call(
            LLMCallParameter(
                input=self.session.conversation_history,
                system=self.session.system_prompt,
            )
        ):
            match response_item:
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
        if turn_reasoning_items:
            self.session.append_history([turn_reasoning_items])
        if turn_assistant_message:
            self.session.append_history([turn_assistant_message])
        if turn_tool_calls:
            self.session.append_history(turn_tool_calls)

        if turn_tool_calls:
            # TODO: call tools
            pass
