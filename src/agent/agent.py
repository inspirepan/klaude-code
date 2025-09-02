from collections.abc import AsyncGenerator
from pathlib import Path

from src.config import Config
from src.llm.client import LLMClient
from src.llm.registry import create_llm_client
from src.protocal import AssistantMessageDeltaEvent, AssistantMessageEvent, Event
from src.session import Session


class Agent:
    def __init__(self, config: Config, session_id: str | None = None):
        work_dir: Path = Path.cwd()
        self.session: Session = (
            Session(work_dir=work_dir)
            if session_id is None
            else Session.load(session_id)
        )
        self.llm_client: LLMClient = create_llm_client(config.protocal, config)

    async def run_task(self, user_input: str) -> AsyncGenerator[Event, None]:
        print(user_input)
        mock_response = """This is a mock response from the agent."""
        for word in mock_response.split(" "):
            yield AssistantMessageDeltaEvent(id="", session_id="", content=word)
        yield AssistantMessageEvent(id="", session_id="", content=mock_response)

    async def run_turn(self) -> AsyncGenerator[Event, None]:
        yield AssistantMessageEvent(id="", session_id="", content="")
