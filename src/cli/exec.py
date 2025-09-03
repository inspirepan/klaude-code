import asyncio
from asyncio import Queue

from src.agent import Agent
from src.agent.tool import BASH_TOOL_NAME, get_tool_schemas
from src.config import load_config
from src.llm import LLMClient, create_llm_client
from src.protocol import EndEvent, Event
from src.ui import REPLDisplay


async def exec_once(user_input: str) -> None:
    config = load_config()
    llm_client: LLMClient = create_llm_client(config.llm_config)
    agent: Agent = Agent(
        llm_client=llm_client, tools=get_tool_schemas([BASH_TOOL_NAME])
    )

    q: Queue[Event] = Queue()
    display = REPLDisplay()
    display_task = asyncio.create_task(display.consume_event_loop(q))

    try:
        async for event in agent.run_task(user_input):
            await q.put(event)
        await q.join()
    finally:
        # Ensure display loop terminates
        await q.put(EndEvent())
        await display_task
