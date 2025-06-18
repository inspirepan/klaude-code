from typing import Any, List, Optional
import time
import asyncio
from pydantic import BaseModel
from rich.live import Live
from rich.columns import Columns


from .config import ConfigModel
from .input import Commands, InputSession, UserInput
from .llm import AgentLLM
from .message import (AIMessage, BasicMessage, UserMessage, ToolCallMessage)
from .session import Session
from .tools.bash import BashTool
from .tool import Tool
from .tui import console, render_message, render_suffix


DEFAULT_MAX_STEPS = 80
INTERACTIVE_MAX_STEPS = 100
TOKEN_WARNING_THRESHOLD = 0.8
TODO_SUGGESTION_LENGTH_THRESHOLD = 40

BASIC_TOOL_SET = [BashTool]


class Agent:
    def __init__(
        self,
        session: Session,
        config: ConfigModel,
        label: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        with_agent_tool: bool = False,
        with_todo_tool: bool = False,
    ):
        self.session: Session = session
        self.label = label
        self.input_session = InputSession(session.work_dir)
        self.print_trace = True
        self.config: ConfigModel = config
        self.tools = tools
        self.comand_handler = CommandHandler(self)
        self.tool_handler = ToolHandler(self, self.tools)

    async def chat_interactive(self):
        while True:
            user_input: UserInput = await self.input_session.prompt_async()
            cmd_res = self.comand_handler.handle(user_input)
            if cmd_res.command_result:
                console.print(render_suffix(cmd_res.command_result))
            self.append_message(
                UserMessage(content=cmd_res.user_input, mode=user_input.mode.value, suffix=cmd_res.command_result),
                print_msg=False
            )
            if cmd_res.need_agent_run:
                if not cmd_res.user_input:
                    continue
                await self.run(max_steps=INTERACTIVE_MAX_STEPS)

    async def run(self, max_steps: int = DEFAULT_MAX_STEPS):
        for _ in range(max_steps):
            llm_response = await AgentLLM.call(
                msgs=[m.to_openai() for m in self.session.messages],
                tools=[tool.openai_schema() for tool in self.tools]
            )
            ai_message: AIMessage = AIMessage.from_llm_response(llm_response)
            self.append_message(ai_message)
            if llm_response.finish_reason == "stop":
                return llm_response.content
            if llm_response.finish_reason == "tool_calls" or len(llm_response.tool_calls) > 0:
                await self.tool_handler.handle(ai_message)
                break

        max_step_msg = f"Max steps {max_steps} reached"
        console.print(render_message(max_step_msg, mark_style="blue"))
        return max_step_msg

    def append_message(self, msg: BasicMessage, print_msg=True):
        self.session.append_message(msg)
        if self.print_trace:
            if print_msg:
                console.print(msg)
            console.print()


def get_main_agent(session: Session, config: ConfigModel) -> Agent:
    return Agent(session, config, tools=BASIC_TOOL_SET)


class CommandHandler:
    def __init__(self, agent):
        self.agent: Agent = agent

    class CommandResult(BaseModel):
        user_input: str
        command_result: Any
        need_agent_run: bool = False

    def handle(self, user_input: UserInput) -> 'CommandHandler.CommandResult':
        if not user_input.command:
            return self.CommandResult(user_input=user_input.content, command_result="", need_agent_run=True)
        if user_input.command == Commands.STATUS:
            return self.CommandResult(user_input=user_input.content, command_result=self.agent.config, need_agent_run=False)
        return self.CommandResult(user_input=user_input.content, command_result="", need_agent_run=False)


class ToolHandler:
    def __init__(self, agent, tools: List[Tool]):
        self.agent: Agent = agent
        self.tool_dict = {tool.name: tool for tool in tools} if tools else {}

    async def handle(self, ai_message: AIMessage):
        if not ai_message.tool_calls or not len(ai_message.tool_calls):
            return

        parallelable_tool_calls = []
        non_parallelable_tool_calls = []
        for tool_call in ai_message.tool_calls.values():
            if tool_call.tool_name not in self.tool_dict:
                pass
            if self.tool_dict[tool_call.tool_name].is_parallelable():
                parallelable_tool_calls.append(tool_call)
            else:
                non_parallelable_tool_calls.append(tool_call)

        await self.handle_parallel_tool_call(parallelable_tool_calls)

        for tc in non_parallelable_tool_calls:
            await self.handle_single_tool_call(tc)

    async def handle_parallel_tool_call(self, tool_calls: List[ToolCallMessage]):
        tool_instances = [self.tool_dict[tc.tool_name].create_instance(tc) for tc in tool_calls]

        with Live(refresh_per_second=3, console=console.console) as live:
            show_once = False
            for ti in tool_instances:
                ti.start_thread()
            while all(ti.is_running() for ti in tool_instances) or not show_once:
                columns = Columns([ti.get_tool_message() for ti in tool_instances], expand=False, equal=False)
                live.update(columns)
                show_once = True
                await asyncio.sleep(0.3)
        for ti in tool_instances:
            ti.join()

    async def handle_single_tool_call(self, tool_call: ToolCallMessage):
        pass
