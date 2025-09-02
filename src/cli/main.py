import asyncio
from typing import AsyncGenerator

from prompt_toolkit import PromptSession

from src.agent import Agent
from src.protocal import EndEvent, Event
from src.ui import StdoutDisplay


async def forward_event(gen: AsyncGenerator[Event, None], q: asyncio.Queue[Event]) -> None:
    try:
        async for event in gen:
            await q.put(event)
    except Exception as e:
        raise e
    finally:
        await q.put(EndEvent())


async def run_interactive():
    session: PromptSession = PromptSession()
    agent: Agent = Agent()
    display: StdoutDisplay = StdoutDisplay()
    q: asyncio.Queue[Event] = asyncio.Queue()

    while True:
        user_input = await session.prompt_async("> ")
        if user_input == "exit":
            break

        async with asyncio.TaskGroup() as tg:
            tg.create_task(forward_event(agent.run_task(user_input), q))
            tg.create_task(display.consume_event_loop(q))
        await q.join()


def main():
    asyncio.run(run_interactive())


if __name__ == "__main__":
    main()
