from typing import Any, List, Optional

from pydantic import BaseModel

from .config import ConfigModel
from .input import Commands, InputSession, UserInput
from .llm import AgentLLM
from .message import AIMessage, BasicMessage, UserMessage
from .session import Session
from .tool import Tool, ToolHandler
from .tools.bash import BashTool
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
        self.print_switch = True
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
            console.print()
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

        max_step_msg = f"Max steps {max_steps} reached"
        console.print(render_message(max_step_msg, mark_style="blue"))
        console.print()
        return max_step_msg

    def append_message(self, *msgs: BasicMessage, print_msg=True):
        self.session.append_message(*msgs)
        if self.print_switch:
            if print_msg:
                for msg in msgs:
                    console.print(msg)


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
