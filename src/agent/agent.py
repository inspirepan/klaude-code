from typing import AsyncGenerator

from src.protocal import AssistantMessageDeltaEvent, AssistantMessageEvent, Event


class Agent:
    def __init__(self):
        pass

    async def run_task(self, user_input: str) -> AsyncGenerator[Event, None]:
        mock_response = """This is a mock response from the agent."""
        for word in mock_response.split(" "):
            yield AssistantMessageDeltaEvent(id="", session_id="", content=word)
        yield AssistantMessageEvent(id="", session_id="", content=mock_response)

    async def run_turn(self) -> AsyncGenerator[Event, None]:
        yield AssistantMessageEvent(id="", session_id="", content="")
