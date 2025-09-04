import asyncio
from asyncio import Queue

from codex_mini.config import load_config
from codex_mini.core import Agent
from codex_mini.core.tool import BASH_TOOL_NAME, get_tool_schemas
from codex_mini.llm import LLMClient, create_llm_client
from codex_mini.protocol import EndEvent, Event
from codex_mini.ui import REPLDisplay


async def exec_once(user_input: str) -> None:
    config = load_config()
    llm_client: LLMClient = create_llm_client(config.get_main_model_config())
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
