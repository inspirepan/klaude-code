import asyncio
import os
from typing import Annotated, Any, List, Optional

from pydantic import BaseModel, Field

from .config import ConfigModel
from .input import Commands, InputSession, UserInput
from .llm import AgentLLM
from .message import (
    AIMessage,
    BasicMessage,
    SystemMessage,
    ToolCallMessage,
    UserMessage,
)
from .prompt import AGENT_TOOL_DESC, SUB_AGENT_TASK_USER_PROMPT
from .session import Session
from .tool import Tool, ToolHandler, ToolInstance
from .tools.bash import BashTool
from .tui import console, render_message, render_suffix

DEFAULT_MAX_STEPS = 80
INTERACTIVE_MAX_STEPS = 100
TOKEN_WARNING_THRESHOLD = 0.8
TODO_SUGGESTION_LENGTH_THRESHOLD = 40

BASIC_TOOLS = [BashTool]


class Agent(Tool):
    def __init__(
        self,
        session: Session,
        config: Optional[ConfigModel] = None,
        label: Optional[str] = None,
        tools: Optional[List[Tool]] = None,
        with_agent_tool: bool = False,
        with_todo_tool: bool = False,
        print_switch: bool = True,
    ):
        self.session: Session = session
        self.label = label
        self.input_session = InputSession(session.work_dir)
        self.print_switch = print_switch
        self.config: Optional[ConfigModel] = config
        self.tools = tools
        self.comand_handler = CommandHandler(self)
        self.tool_handler = ToolHandler(self, self.tools, show_live=print_switch)

    async def chat_interactive(self):
        while True:
            user_input: UserInput = await self.input_session.prompt_async()
            cmd_res = self.comand_handler.handle(user_input)
            if cmd_res.command_result:
                console.print(render_suffix(cmd_res.command_result))
            self.append_message(
                UserMessage(
                    content=cmd_res.user_input,
                    mode=user_input.mode.value,
                    suffix=cmd_res.command_result,
                ),
                print_msg=False,
            )
            console.print()
            if cmd_res.need_agent_run:
                if not cmd_res.user_input:
                    continue
                await self.run(max_steps=INTERACTIVE_MAX_STEPS)

    async def run(self, max_steps: int = DEFAULT_MAX_STEPS):
        for _ in range(max_steps):
            ai_msg = await AgentLLM.call(
                msgs=self.session.messages,
                tools=self.tools,
                show_status=self.print_switch,
            )
            self.append_message(ai_msg)
            if ai_msg.finish_reason == 'stop':
                return ai_msg.content
            if ai_msg.finish_reason == 'tool_calls' or len(ai_msg.tool_calls) > 0:
                await self.tool_handler.handle(ai_msg)

        max_step_msg = f'Max steps {max_steps} reached'
        console.print(render_message(max_step_msg, mark_style='blue'))
        console.print()
        return max_step_msg

    def append_message(self, *msgs: BasicMessage, print_msg=True):
        self.session.append_message(*msgs)
        if self.print_switch:
            if print_msg:
                for msg in msgs:
                    console.print(msg)

    # Implement SubAgent
    # ------------------
    name = 'Agent'
    desc = AGENT_TOOL_DESC

    class Input(BaseModel):
        description: Annotated[str, Field(description='A short (3-5 word) description of the task')] = None
        prompt: Annotated[str, Field(description='The task for the agent to perform')]

        def __str__(self):
            return f'{self.description.strip()}: {self.prompt.strip()}'

    @classmethod
    def invoke(cls, tool_call: ToolCallMessage, instance: 'ToolInstance'):
        args: 'Agent.Input' = cls.parse_input_args(tool_call)
        from rich.panel import Panel
        from rich.text import Text
        from rich.padding import Padding
        from rich.box import HORIZONTALS

        tool_call.rich_args = Padding.indent(
            Panel.fit(args.prompt, title=Text(args.description, style='bold'), box=HORIZONTALS),
            level=2,
        )

        def subagent_append_message_hook(*msgs: BasicMessage) -> None:
            if not msgs:
                return
            for msg in msgs:
                if not isinstance(msg, AIMessage):
                    continue
                if msg.tool_calls:
                    instance.tool_result().subagent_tool_calls.extend(msg.tool_calls.values())

        session = Session(
            work_dir=os.getcwd(),
            messages=[SystemMessage(content="You are a helpful assistant run in user's terminal")],
            append_message_hook=subagent_append_message_hook,
        )
        agent = cls(session, tools=BASIC_TOOLS, print_switch=False)
        agent.append_message(
            UserMessage(content=SUB_AGENT_TASK_USER_PROMPT.format(description=args.description, prompt=args.prompt)),
            print_msg=False,
        )
        result = asyncio.run(agent.run(max_steps=DEFAULT_MAX_STEPS))
        instance.tool_result().content = result.strip()


def get_main_agent(session: Session, config: ConfigModel) -> Agent:
    return Agent(session, config, tools=BASIC_TOOLS + [Agent])


class CommandHandler:
    def __init__(self, agent):
        self.agent: Agent = agent

    class CommandResult(BaseModel):
        user_input: str
        command_result: Any
        need_agent_run: bool = False

    def handle(self, user_input: UserInput) -> 'CommandHandler.CommandResult':
        if not user_input.command:
            return self.CommandResult(user_input=user_input.content, command_result='', need_agent_run=True)
        if user_input.command == Commands.STATUS:
            return self.CommandResult(
                user_input=user_input.content,
                command_result=self.agent.config,
                need_agent_run=False,
            )
        return self.CommandResult(user_input=user_input.content, command_result='', need_agent_run=False)
