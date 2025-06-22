import asyncio
import os
from typing import Annotated, List, Optional

from anthropic import AnthropicError
from openai import OpenAIError
from pydantic import BaseModel, Field
from rich.box import HORIZONTALS
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from .config import ConfigModel
from .llm import AgentLLM
from .message import INTERRUPTED_MSG, AIMessage, BasicMessage, SystemMessage, ToolCall, ToolMessage, UserMessage, InterruptedMessage, register_tool_call_renderer, register_tool_result_renderer
from .prompt.system import SUB_AGENT_SYSTEM_PROMPT, SUB_AGENT_TASK_USER_PROMPT
from .prompt.tools import AGENT_TOOL_DESC, CODE_SEARCH_AGENT_TOOL_DESC
from .session import Session
from .tool import Tool, ToolHandler, ToolInstance
from .tools import BashTool, EditTool, LsTool, MultiEditTool, ReadTool, TodoReadTool, TodoWriteTool, WriteTool
from .tui import clean_last_line, console, format_style, render_markdown, render_message, render_suffix
from .user_input import UserInputHandler, InputSession, UserInput

DEFAULT_MAX_STEPS = 80
INTERACTIVE_MAX_STEPS = 100
TOKEN_WARNING_THRESHOLD = 0.8
TODO_SUGGESTION_LENGTH_THRESHOLD = 40

BASIC_TOOLS = [LsTool, ReadTool, EditTool, MultiEditTool, WriteTool, BashTool]
READ_ONLY_TOOLS = [ReadTool, BashTool]

QUIT = ['quit', 'exit', 'q']


class Agent(Tool):
    def __init__(
        self,
        session: Session,
        config: Optional[ConfigModel] = None,
        label: Optional[str] = None,
        availiable_tools: Optional[List[Tool]] = None,
        print_switch: bool = True,
    ):
        self.session: Session = session
        self.label = label
        self.input_session = InputSession(session.work_dir)
        self.print_switch = print_switch
        self.config: Optional[ConfigModel] = config
        self.availiable_tools = availiable_tools
        self.user_input_handler = UserInputHandler(self)
        self.tool_handler = ToolHandler(self, self.availiable_tools, show_live=print_switch)

    async def chat_interactive(self):
        while True:
            user_input: UserInput = await self.input_session.prompt_async()
            if user_input.raw_input.strip().lower() in QUIT:
                break
            need_agent_run = self.user_input_handler.handle(user_input)
            console.print()
            if need_agent_run:
                await self.run(max_steps=INTERACTIVE_MAX_STEPS, tools=self.availiable_tools)

    async def run(self, max_steps: int = DEFAULT_MAX_STEPS, parent_tool_instance: Optional['ToolInstance'] = None, tools: Optional[List[Tool]] = None):
        try:
            for _ in range(max_steps):
                # Check if task was canceled (for subagent execution)
                if parent_tool_instance and parent_tool_instance.tool_result().tool_call.status == 'canceled':
                    return INTERRUPTED_MSG
                ai_msg = await AgentLLM.call(
                    msgs=self.session.messages,
                    tools=tools,
                    show_status=self.print_switch,
                )
                self.append_message(ai_msg)
                if ai_msg.finish_reason == 'stop':
                    return ai_msg.content or ''
                if ai_msg.finish_reason == 'tool_calls' or len(ai_msg.tool_calls) > 0:
                    await self.tool_handler.handle(ai_msg)

        except (OpenAIError, AnthropicError) as e:
            clean_last_line()
            console.print(render_suffix(f'LLM error: {str(e)}', style='red'))
            console.print()
            return f'LLM error: {str(e)}'
        except (KeyboardInterrupt, asyncio.CancelledError):
            return self._handle_interruption()
        max_step_msg = f'Max steps {max_steps} reached'
        if self.print_switch:
            console.print(render_message(max_step_msg, mark_style='blue'))
            console.print()
        return max_step_msg

    def append_message(self, *msgs: BasicMessage, print_msg=True):
        self.session.append_message(*msgs)
        if self.print_switch:
            if print_msg:
                for msg in msgs:
                    console.print(msg)

    def _handle_interruption(self):
        asyncio.create_task(asyncio.sleep(0.1))
        if hasattr(console.console, '_live'):
            try:
                console.console._live.stop()
            except BaseException:
                pass
        console.console.print('', end='\r')
        console.print()
        self.append_message(InterruptedMessage())
        return INTERRUPTED_MSG

    # Implement SubAgent
    # ------------------
    name = 'Agent'
    desc = AGENT_TOOL_DESC

    class Input(BaseModel):
        description: Annotated[str, Field(description='A short (3-5 word) description of the task')] = None
        prompt: Annotated[str, Field(description='The task for the agent to perform')]

    @classmethod
    def get_subagent_tools(cls):
        return BASIC_TOOLS

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'Agent.Input' = cls.parse_input_args(tool_call)

        def subagent_append_message_hook(*msgs: BasicMessage) -> None:
            if not msgs:
                return
            for msg in msgs:
                if not isinstance(msg, AIMessage):
                    continue
                if msg.tool_calls:
                    for tool_call in msg.tool_calls.values():
                        instance.tool_result().append_extra_data('tool_calls', tool_call.model_dump())

        session = Session(
            work_dir=os.getcwd(),
            messages=[SystemMessage(content=SUB_AGENT_SYSTEM_PROMPT, cached=True)],
            append_message_hook=subagent_append_message_hook,
            source='subagent',
        )
        agent = cls(session, availiable_tools=cls.get_subagent_tools(), print_switch=False)
        agent.append_message(
            UserMessage(content=SUB_AGENT_TASK_USER_PROMPT.format(description=args.description, prompt=args.prompt)),
            print_msg=False,
        )

        result = asyncio.run(agent.run(max_steps=DEFAULT_MAX_STEPS, parent_tool_instance=instance, tools=cls.get_subagent_tools()))
        instance.tool_result().set_content((result or '').strip())


class CodeSearchAgentTool(Agent):
    name = 'CodeSearchAgent'
    desc = CODE_SEARCH_AGENT_TOOL_DESC

    @classmethod
    def get_subagent_tools(cls):
        return READ_ONLY_TOOLS


def render_agent_args(tool_call: ToolCall):
    yield format_style(tool_call.tool_name, 'bold')
    yield Padding.indent(
        Panel.fit(
            tool_call.tool_args_dict['prompt'],
            title=Text(tool_call.tool_args_dict['description'], style='bold'),
            box=HORIZONTALS,
        ),
        level=2,
    )


def render_agent_result(tool_msg: ToolMessage):
    tool_calls = tool_msg.get_extra_data('tool_calls')
    if tool_calls:
        for subagent_tool_call_dcit in tool_calls:
            tool_call = ToolCall(**subagent_tool_call_dcit)
            for item in tool_call.get_suffix_renderable():
                yield render_suffix(item)
    if tool_msg.content:
        yield render_suffix(Panel.fit(render_markdown(tool_msg.content), border_style='agent_result'))


register_tool_call_renderer('Agent', render_agent_args)
register_tool_result_renderer('Agent', render_agent_result)
register_tool_call_renderer('CodeSearchAgent', render_agent_args)
register_tool_result_renderer('CodeSearchAgent', render_agent_result)


def get_main_agent(session: Session, config: ConfigModel) -> Agent:
    return Agent(session, config, availiable_tools=BASIC_TOOLS + [Agent, TodoWriteTool, TodoReadTool])
