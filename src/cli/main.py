import asyncio
from collections.abc import AsyncGenerator

from prompt_toolkit import PromptSession

from src.agent import Agent
from src.config import load_config
from src.llm import LLMClient, create_llm_client
from src.protocal import EndEvent, Event
from src.trace.log import log
from src.ui import StdoutDisplay


async def forward_event(gen: AsyncGenerator[Event, None], q: asyncio.Queue[Event]):
    try:
        async for event in gen:
            await q.put(event)
    except Exception as e:
        raise e
    finally:
        await q.put(EndEvent())


async def run_interactive():
    session: PromptSession[str] = PromptSession()
    config = load_config()
    llm_client: LLMClient = create_llm_client(config.llm_config)
    agent: Agent = Agent(llm_client=llm_client)
    display: StdoutDisplay = StdoutDisplay()
    q: asyncio.Queue[Event] = asyncio.Queue()

    try:
        while True:
            user_input: str = await session.prompt_async("> ")
            if user_input == "exit":
                break

            async with asyncio.TaskGroup() as tg:
                _ = tg.create_task(forward_event(agent.run_task(user_input), q))
                _ = tg.create_task(display.consume_event_loop(q))
            await q.join()
    except KeyboardInterrupt:
        log("Bye!")


def main():
    asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
