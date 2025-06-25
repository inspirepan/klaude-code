import asyncio
import json
import os
from typing import Annotated, List, Optional

from anthropic import AnthropicError
from openai import OpenAIError
from pydantic import BaseModel, Field
from rich.box import HORIZONTALS
from rich.console import Group
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from . import command  # noqa: F401 # import user_command to trigger command registration
from .config import ConfigModel
from .llm import AgentLLM
from .mcp.mcp_tool import MCPManager
from .message import (
    INTERRUPTED_MSG,
    AIMessage,
    BasicMessage,
    SpecialUserMessageTypeEnum,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
    register_tool_call_renderer,
    register_tool_result_renderer,
)
from .prompt.plan_mode import APPROVE_MSG, PLAN_MODE_REMINDER, REJECT_MSG
from .prompt.reminder import EMPTY_TODO_REMINDER, TODO_REMINDER, get_context_reminder
from .prompt.system import get_subagent_system_prompt
from .prompt.tools import CODE_SEARCH_TASK_TOOL_DESC, TASK_TOOL_DESC
from .session import Session
from .tool import Tool, ToolHandler, ToolInstance
from .tools import BashTool, EditTool, ExitPlanModeTool, GlobTool, GrepTool, LsTool, MultiEditTool, ReadTool, TodoReadTool, TodoWriteTool, WriteTool
from .tui import INTERRUPT_TIP, ColorStyle, clear_last_line, console, render_hello, render_markdown, render_message, render_status, render_suffix
from .user_input import _INPUT_MODES, NORMAL_MODE_NAME, InputSession, UserInputHandler
from .user_questionary import user_select

DEFAULT_MAX_STEPS = 80
INTERACTIVE_MAX_STEPS = 100
TOKEN_WARNING_THRESHOLD = 0.9
TODO_SUGGESTION_LENGTH_THRESHOLD = 40

BASIC_TOOLS = [LsTool, GrepTool, GlobTool, ReadTool, EditTool, MultiEditTool, WriteTool, BashTool, TodoWriteTool, TodoReadTool, ExitPlanModeTool]
READ_ONLY_TOOLS = [LsTool, GrepTool, GlobTool, ReadTool, TodoWriteTool, TodoReadTool]

QUIT_COMMAND = ['quit', 'exit']


class Agent(Tool):
    def __init__(
        self,
        session: Session,
        config: Optional[ConfigModel] = None,
        label: Optional[str] = None,
        availiable_tools: Optional[List[Tool]] = None,
        print_switch: bool = True,
        enable_claudemd_reminder: bool = True,
        enable_todo_reminder: bool = True,
        enable_mcp: bool = True,
        enable_plan_mode_reminder: bool = True,
    ):
        self.session: Session = session
        self.label = label
        self.input_session = InputSession(session.work_dir)
        self.print_switch = print_switch
        self.config: Optional[ConfigModel] = config
        self.availiable_tools = availiable_tools
        self.user_input_handler = UserInputHandler(self)
        self.tool_handler = ToolHandler(self, self.availiable_tools or [], show_live=print_switch)
        self.enable_claudemd_reminder = enable_claudemd_reminder
        self.enable_todo_reminder = enable_todo_reminder
        self.enable_mcp = enable_mcp
        self.mcp_manager: Optional[MCPManager] = None
        self.plan_mode_activated: bool = False
        self.enable_plan_mode_reminder = enable_plan_mode_reminder

    async def chat_interactive(self, first_message: str = None):
        self._initialize_llm()
        console.print(render_hello())

        # Initialize MCP
        if self.enable_mcp:
            await self._initialize_mcp()

        self.session.messages.print_all_message()  # For continue and resume scene.
        epoch = 0
        try:
            while True:
                if epoch == 0 and first_message:
                    user_input_text = first_message
                else:
                    user_input_text = await self.input_session.prompt_async()
                if user_input_text.strip().lower() in QUIT_COMMAND:
                    break
                need_agent_run = await self.user_input_handler.handle(user_input_text, print_msg=bool(first_message))
                console.print()
                if epoch == 0 and self.enable_claudemd_reminder:
                    self._handle_caludemd_reminder()
                if need_agent_run:
                    await self.run(max_steps=INTERACTIVE_MAX_STEPS, tools=self._get_all_tools())
                else:
                    self.session.save()
                epoch += 1
        finally:
            # Clean up MCP resources
            if self.mcp_manager:
                await self.mcp_manager.shutdown()

    async def _auto_compact_conversation(self, tools: Optional[List[Tool]] = None):
        """Check token count and compact conversation history if necessary"""
        messages_tokens = sum(msg.tokens for msg in self.session.messages)
        tools_tokens = sum(tool.tokens() for tool in (tools or self.tools))
        total_tokens = messages_tokens + tools_tokens
        if not self.config or not self.config.context_window_threshold:
            return
        if total_tokens > self.config.context_window_threshold.value * TOKEN_WARNING_THRESHOLD:
            clear_last_line()
            console.print(Text(f'Notice: total_tokens: {total_tokens}, context_window_threshold: {self.config.context_window_threshold.value}\n', style=ColorStyle.WARNING.value))
        if total_tokens > self.config.context_window_threshold.value:
            await self.session.compact_conversation_history(show_status=self.print_switch)

    async def run(self, max_steps: int = DEFAULT_MAX_STEPS, parent_tool_instance: Optional['ToolInstance'] = None, tools: Optional[List[Tool]] = None):
        try:
            for _ in range(max_steps):
                # Check if task was canceled (for subagent execution)
                if parent_tool_instance and parent_tool_instance.tool_result().tool_call.status == 'canceled':
                    return INTERRUPTED_MSG

                # Check token count and compact if necessary
                await self._auto_compact_conversation(tools)

                if self.enable_todo_reminder:
                    self._handle_todo_reminder()
                if self.enable_plan_mode_reminder:
                    self._handle_plan_mode_reminder()
                self.session.save()
                ai_msg = await AgentLLM.call(
                    msgs=self.session.messages,
                    tools=tools,
                    show_status=self.print_switch,
                )
                self.append_message(ai_msg)
                if ai_msg.finish_reason == 'stop':
                    # Cannot directly use this AI response's content as result,
                    # because Claude might execute a tool call (e.g. TodoWrite) at the end and return empty content
                    last_ai_msg = self.session.messages.get_last_message(role='assistant', filter_empty=True)
                    return last_ai_msg.content if last_ai_msg else ''
                if ai_msg.finish_reason == 'tool_calls' or len(ai_msg.tool_calls) > 0:
                    if not await self._handle_exit_plan_mode(ai_msg.tool_calls):
                        return 'Plan mode maintained, awaiting further instructions.'
                    # Update tool handler with MCP tools
                    self._update_tool_handler_tools(tools)
                    await self.tool_handler.handle(ai_msg)

        except (OpenAIError, AnthropicError) as e:
            clear_last_line()
            console.print(render_suffix(f'LLM error: {str(e)}', style=ColorStyle.ERROR.value))
            console.print()
            return f'LLM error: {str(e)}'
        except (KeyboardInterrupt, asyncio.CancelledError):
            return self._handle_interruption()
        max_step_msg = f'Max steps {max_steps} reached'
        if self.print_switch:
            console.print(render_message(max_step_msg, mark_style=ColorStyle.INFO.value))
            console.print()
        return max_step_msg

    def append_message(self, *msgs: BasicMessage, print_msg=True):
        self.session.append_message(*msgs)
        if self.print_switch:
            if print_msg:
                for msg in msgs:
                    console.print(msg)

    def _handle_todo_reminder(self):
        last_msg = self.session.messages.get_last_message(filter_empty=True)
        if not self.session.todo_list:
            reminder = EMPTY_TODO_REMINDER
            if isinstance(last_msg, (UserMessage, ToolMessage)):
                last_msg.append_post_system_reminder(reminder)
        else:
            has_active_todos = any(todo.status in ['in_progress', 'pending'] for todo in self.session.todo_list.todos)
            if has_active_todos:
                reminder = TODO_REMINDER.format(todo_list_json=json.dumps(self.session.todo_list.model_dump(), ensure_ascii=False, separators=(',', ':')))
                if isinstance(last_msg, ToolMessage):
                    last_msg.append_post_system_reminder(reminder)

    def _handle_plan_mode_reminder(self):
        if not self.plan_mode_activated:
            return
        last_msg = self.session.messages.get_last_message(filter_empty=True)
        if last_msg and isinstance(last_msg, (UserMessage, ToolMessage)):
            last_msg.append_post_system_reminder(PLAN_MODE_REMINDER)

    async def _handle_exit_plan_mode(self, tool_calls: List[ToolCall]) -> bool:
        exit_plan_call: ToolCall = next((call for call in tool_calls.values() if call.tool_name == ExitPlanModeTool.get_name()), None)
        if not exit_plan_call:
            return True
        exit_plan_call.status = 'success'
        console.print(exit_plan_call)
        # Ask user for confirmation
        options = ['Yes', 'No, keep planning']
        selection = await user_select(options, 'Would you like to proceed?')
        approved = selection == 0
        if approved:
            if hasattr(self, 'input_session') and self.input_session:
                self.input_session.current_input_mode = _INPUT_MODES[NORMAL_MODE_NAME]
            self.plan_mode_activated = False
        tool_msg = ToolMessage(tool_call_id=exit_plan_call.id, tool_call_cache=exit_plan_call, content=APPROVE_MSG if approved else REJECT_MSG)
        tool_msg.set_extra_data('approved', approved)
        console.print(*tool_msg.get_suffix_renderable())
        self.append_message(tool_msg, print_msg=False)
        return approved

    def _handle_caludemd_reminder(self):
        reminder = get_context_reminder(self.session.work_dir)
        last_user_msg = self.session.messages.get_last_message(role='user')
        if last_user_msg:
            last_user_msg.append_pre_system_reminder(reminder)

    def _handle_interruption(self):
        asyncio.create_task(asyncio.sleep(0.1))
        if hasattr(console.console, '_live'):
            try:
                console.console._live.stop()
            except BaseException:
                pass
        console.console.print('', end='\r')
        self.append_message(UserMessage(content=INTERRUPTED_MSG, user_msg_type=SpecialUserMessageTypeEnum.INTERRUPTED.value))
        return INTERRUPTED_MSG

    def _initialize_llm(self):
        AgentLLM.initialize(
            model_name=self.config.model_name.value,
            base_url=self.config.base_url.value,
            api_key=self.config.api_key.value,
            model_azure=self.config.model_azure.value,
            max_tokens=self.config.max_tokens.value,
            extra_header=self.config.extra_header.value,
            enable_thinking=self.config.enable_thinking.value,
        )

    async def headless_run(self, user_input_text: str, print_trace: bool = False):
        self._initialize_llm()
        # Initialize MCP
        if self.enable_mcp:
            await self._initialize_mcp()

        try:
            need_agent_run = await self.user_input_handler.handle(user_input_text)
            if not need_agent_run:
                return
            if self.enable_claudemd_reminder:
                self._handle_caludemd_reminder()
            self.print_switch = print_trace
            self.tool_handler.show_live = print_trace
            if print_trace:
                await self.run(tools=self._get_all_tools())
                return
            status = render_status('Running...')
            status.start()
            running = True

            async def update_status():
                while running:
                    tool_msg_count = len([msg for msg in self.session.messages if msg.role == 'tool'])
                    status.update(
                        Group(
                            f'Running... ([bold]{tool_msg_count}[/bold] tool uses)',
                            f'[italic]see more details in session file: {self.session._get_messages_file_path()}[/italic]',
                            Text(INTERRUPT_TIP[1:], style=ColorStyle.MUTED),
                        )
                    )
                    await asyncio.sleep(0.1)

            update_task = asyncio.create_task(update_status())
            try:
                result = await self.run(tools=self._get_all_tools())
            finally:
                running = False
                status.stop()
                update_task.cancel()
                try:
                    await update_task
                except asyncio.CancelledError:
                    pass
            console.print(result)
        finally:
            # Clean up MCP resources
            if self.mcp_manager:
                await self.mcp_manager.shutdown()

    async def _initialize_mcp(self):
        """Initialize MCP manager"""
        if self.mcp_manager is None:
            self.mcp_manager = MCPManager(self.session.work_dir)
            await self.mcp_manager.initialize()

    def _get_all_tools(self) -> List[Tool]:
        """Get all available tools including MCP tools"""
        tools = self.availiable_tools.copy() if self.availiable_tools else []

        # Add MCP tools
        if self.mcp_manager and self.mcp_manager.is_initialized():
            mcp_tools = self.mcp_manager.get_mcp_tools()
            tools.extend(mcp_tools)

        return tools

    def _update_tool_handler_tools(self, tools: List[Tool]):
        """Update ToolHandler's tool dictionary"""
        self.tool_handler.tool_dict = {tool.name: tool for tool in tools} if tools else {}

    # Implement SubAgent
    # ------------------
    name = 'Task'
    desc = TASK_TOOL_DESC
    parallelable: bool = True

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
            messages=[SystemMessage(content=get_subagent_system_prompt(work_dir=instance.parent_agent.session.work_dir, model_name=instance.parent_agent.config.model_name.value))],
            append_message_hook=subagent_append_message_hook,
            source='subagent',
        )
        agent = cls(session, availiable_tools=cls.get_subagent_tools(), print_switch=False, config=instance.parent_agent.config)
        agent.append_message(
            UserMessage(content=args.prompt),
            print_msg=False,
        )

        result = asyncio.run(agent.run(max_steps=DEFAULT_MAX_STEPS, parent_tool_instance=instance, tools=cls.get_subagent_tools()))
        instance.tool_result().set_content((result or '').strip())


class CodeSearchTaskTool(Agent):
    name = 'CodeSearchTask'
    desc = CODE_SEARCH_TASK_TOOL_DESC

    @classmethod
    def get_subagent_tools(cls):
        return READ_ONLY_TOOLS


def render_agent_args(tool_call: ToolCall):
    yield Text(tool_call.tool_name, style='bold')
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
        yield render_suffix(Panel.fit(render_markdown(tool_msg.content), border_style=ColorStyle.AGENT_BORDER))


register_tool_call_renderer('Task', render_agent_args)
register_tool_result_renderer('Task', render_agent_result)
register_tool_call_renderer('CodeSearchTask', render_agent_args)
register_tool_result_renderer('CodeSearchTask', render_agent_result)


def get_main_agent(session: Session, config: ConfigModel, enable_mcp: bool = False) -> Agent:
    return Agent(session, config, availiable_tools=BASIC_TOOLS + [Agent, CodeSearchTaskTool], enable_claudemd_reminder=True, enable_todo_reminder=True, enable_mcp=enable_mcp)
