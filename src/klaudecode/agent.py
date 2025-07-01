import asyncio
import threading
from pathlib import Path
from typing import Annotated, List, Optional

from anthropic import AnthropicError
from openai import OpenAIError
from pydantic import BaseModel, Field
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from . import user_command  # noqa: F401 # import user_command to trigger command registration
from .config import ConfigModel
from .llm import LLMManager
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
from .prompt.reminder import EMPTY_TODO_REMINDER, FILE_DELETED_EXTERNAL_REMINDER, FILE_MODIFIED_EXTERNAL_REMINDER, get_context_reminder
from .prompt.system import get_subagent_system_prompt
from .prompt.tools import CODE_SEARCH_TASK_TOOL_DESC, TASK_TOOL_DESC
from .session import Session
from .tool import Tool, ToolHandler, ToolInstance
from .tools import BashTool, EditTool, ExitPlanModeTool, GlobTool, GrepTool, LsTool, MultiEditTool, ReadTool, TodoReadTool, TodoWriteTool, WriteTool
from .tools.read import execute_read
from .tui import INTERRUPT_TIP, ColorStyle, console, render_grid, render_markdown, render_message, render_status, render_suffix
from .user_command import custom_command_manager
from .user_input import _INPUT_MODES, NORMAL_MODE_NAME, InputSession, UserInputHandler, user_select

DEFAULT_MAX_STEPS = 80
INTERACTIVE_MAX_STEPS = 100
TOKEN_WARNING_THRESHOLD = 0.85
COMPACT_THRESHOLD = 0.9
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
        self.mcp_manager: Optional[MCPManager] = None
        self.plan_mode_activated: bool = False
        self.enable_plan_mode_reminder = enable_plan_mode_reminder
        self.llm_manager: Optional[LLMManager] = None
        self._interrupt_flag = threading.Event()  # Global interrupt flag for this agent

        # Initialize custom commands
        try:
            custom_command_manager.discover_and_register_commands(session.work_dir)
        except Exception as e:
            if self.print_switch:
                import traceback

                traceback.print_exc()
                console.print(f'Warning: Failed to load custom commands: {e}', style=ColorStyle.WARNING.value)

    async def chat_interactive(self, first_message: str = None):
        self._initialize_llm()

        self.session.messages.print_all_message()  # For continue and resume scene.

        epoch = 0
        try:
            while True:
                # Clear interrupt flag at the start of each interaction
                self._clear_interrupt()

                if epoch == 0 and first_message:
                    user_input_text = first_message
                else:
                    user_input_text = await self.input_session.prompt_async()
                if user_input_text.strip().lower() in QUIT_COMMAND:
                    break
                need_agent_run = await self.user_input_handler.handle(user_input_text, print_msg=bool(first_message))
                if need_agent_run:
                    await self.run(max_steps=INTERACTIVE_MAX_STEPS, tools=self._get_all_tools())
                else:
                    self.session.save()
                epoch += 1
        finally:
            self.session.save()
            # Clean up MCP resources
            if self.mcp_manager:
                await self.mcp_manager.shutdown()

    async def run(self, max_steps: int = DEFAULT_MAX_STEPS, parent_tool_instance: Optional['ToolInstance'] = None, tools: Optional[List[Tool]] = None):
        try:
            self._handle_claudemd_reminder()
            self._handle_empty_todo_reminder()
            for _ in range(max_steps):
                # Check if task was canceled (for subagent execution)
                if parent_tool_instance and parent_tool_instance.tool_result().tool_call.status == 'canceled':
                    return INTERRUPTED_MSG

                # Check token count and compact if necessary
                await self._auto_compact_conversation(tools)

                if self.enable_plan_mode_reminder:
                    self._handle_plan_mode_reminder()
                self._handle_file_external_modified_reminder()

                self.session.save()

                ai_msg = await self.llm_manager.call(
                    msgs=self.session.messages,
                    tools=tools,
                    show_status=self.print_switch,
                    interrupt_check=self._should_interrupt,
                )

                self.session.append_message(ai_msg)
                if ai_msg.finish_reason == 'stop':
                    # Cannot directly use this AI response's content as result,
                    # because Claude might execute a tool call (e.g. TodoWrite) at the end and return empty content
                    last_ai_msg = self.session.messages.get_last_message(role='assistant', filter_empty=True)
                    self.session.save()
                    return last_ai_msg.content if last_ai_msg else ''
                if ai_msg.finish_reason == 'tool_calls' or len(ai_msg.tool_calls) > 0:
                    if not await self._handle_exit_plan_mode(ai_msg.tool_calls):
                        return 'Plan mode maintained, awaiting further instructions.'
                    # Update tool handler with MCP tools
                    self._update_tool_handler_tools(tools)
                    await self.tool_handler.handle(ai_msg)

        except (OpenAIError, AnthropicError) as e:
            console.print(render_suffix(f'LLM error: {str(e)}', style=ColorStyle.ERROR.value))
            return f'LLM error: {str(e)}'
        except (KeyboardInterrupt, asyncio.CancelledError):
            # Clear any live displays before handling interruption
            return self._handle_interruption()
        except Exception as e:
            import traceback

            traceback.print_exc()
            console.print(render_suffix(f'Error: {str(e)}', style=ColorStyle.ERROR.value))
            return f'Error: {str(e)}'
        max_step_msg = f'Max steps {max_steps} reached'
        if self.print_switch:
            console.print(render_message(max_step_msg, mark_style=ColorStyle.INFO.value))
        return max_step_msg

    def _handle_claudemd_reminder(self):
        reminder = get_context_reminder(self.session.work_dir)
        last_user_msg = self.session.messages.get_last_message(role='user')
        if last_user_msg and isinstance(last_user_msg, UserMessage):
            last_user_msg.append_pre_system_reminder(reminder)

    def _handle_empty_todo_reminder(self):
        if TodoWriteTool in self.availiable_tools:
            last_msg = self.session.messages.get_last_message(filter_empty=True)
            if last_msg and isinstance(last_msg, (UserMessage, ToolMessage)):
                last_msg.append_post_system_reminder(EMPTY_TODO_REMINDER)

    def _handle_plan_mode_reminder(self):
        if not self.plan_mode_activated:
            return
        last_msg = self.session.messages.get_last_message(filter_empty=True)
        if last_msg and isinstance(last_msg, (UserMessage, ToolMessage)):
            last_msg.append_post_system_reminder(PLAN_MODE_REMINDER)

    def _handle_file_external_modified_reminder(self):
        modified_files = self.session.file_tracker.get_all_modified()
        if not modified_files:
            return

        last_msg = self.session.messages.get_last_message(filter_empty=True)
        if not last_msg or not isinstance(last_msg, (UserMessage, ToolMessage)):
            return

        for file_path in modified_files:
            try:
                result = execute_read(file_path, tracker=self.session.file_tracker)
                if result.success:
                    reminder = FILE_MODIFIED_EXTERNAL_REMINDER.format(file_path=file_path, file_content=result.content)
                    last_msg.append_post_system_reminder(reminder)
                else:
                    reminder = FILE_DELETED_EXTERNAL_REMINDER.format(file_path=file_path)
                    last_msg.append_post_system_reminder(reminder)
            except Exception:
                reminder = FILE_DELETED_EXTERNAL_REMINDER.format(file_path=file_path)
                last_msg.append_post_system_reminder(reminder)

    async def _handle_exit_plan_mode(self, tool_calls: List[ToolCall]) -> bool:
        exit_plan_call: Optional[ToolCall] = next((call for call in tool_calls.values() if call.tool_name == ExitPlanModeTool.get_name()), None)
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
        self.session.append_message(tool_msg)
        return approved

    def _handle_interruption(self):
        # Set the interrupt flag
        self._interrupt_flag.set()

        # Clean up any live displays
        asyncio.create_task(asyncio.sleep(0.1))
        if hasattr(console.console, '_live') and console.console._live:
            try:
                console.console._live.stop()
            except Exception as e:
                console.print(f'Error stopping live display: {e}')
                pass

        # Add interrupted message
        user_msg = UserMessage(content=INTERRUPTED_MSG, user_msg_type=SpecialUserMessageTypeEnum.INTERRUPTED.value)
        console.print(user_msg)
        self.session.append_message(user_msg)
        return INTERRUPTED_MSG

    def _should_interrupt(self) -> bool:
        """Check if the agent should be interrupted"""
        return self._interrupt_flag.is_set()

    def _clear_interrupt(self):
        """Clear the interrupt flag (for testing or reset)"""
        self._interrupt_flag.clear()

    def _initialize_llm(self):
        if not self.llm_manager:
            self.llm_manager = LLMManager()
        self.llm_manager.initialize_from_config(self.config)

    async def _auto_compact_conversation(self, tools: Optional[List[Tool]] = None):
        """Check token count and compact conversation history if necessary"""
        messages_tokens = sum(msg.tokens for msg in self.session.messages if msg)
        tools_tokens = sum(tool.tokens() for tool in (tools or self.tools))
        total_tokens = messages_tokens + tools_tokens
        if not self.config or not self.config.context_window_threshold:
            return
        if total_tokens > self.config.context_window_threshold.value * TOKEN_WARNING_THRESHOLD:
            console.print(Text(f'Notice: total_tokens: {total_tokens}, context_window_threshold: {self.config.context_window_threshold.value}\n', style=ColorStyle.WARNING.value))
        if total_tokens > self.config.context_window_threshold.value * COMPACT_THRESHOLD:
            await self.session.compact_conversation_history(show_status=self.print_switch, llm_manager=self.llm_manager)

    async def headless_run(self, user_input_text: str, print_trace: bool = False):
        self._initialize_llm()

        try:
            # Clear any previous interrupt state
            self._clear_interrupt()
            need_agent_run = await self.user_input_handler.handle(user_input_text, print_msg=False)
            if not need_agent_run:
                return
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
                            '',
                            render_grid([['details:', Text(str(self.session._get_messages_file_path()), style=ColorStyle.MUTED)]]),
                            '',
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
            self.session.save()
            # Clean up MCP resources
            if self.mcp_manager:
                await self.mcp_manager.shutdown()

    async def initialize_mcp(self) -> bool:
        """Initialize MCP manager"""
        if self.mcp_manager is None:
            self.mcp_manager = MCPManager(self.session.work_dir)
            return await self.mcp_manager.initialize()
        return True

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

    # Implement Agent as tool
    # ------------------------------------------------------
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
            work_dir=Path.cwd(),
            messages=[SystemMessage(content=get_subagent_system_prompt(work_dir=instance.parent_agent.session.work_dir, model_name=instance.parent_agent.config.model_name.value))],
            append_message_hook=subagent_append_message_hook,
            source='subagent',
        )
        agent = cls(session, availiable_tools=cls.get_subagent_tools(), print_switch=False, config=instance.parent_agent.config)
        # Initialize LLM manager for subagent
        agent._initialize_llm()
        agent.session.append_message(UserMessage(content=args.prompt))

        # Use asyncio.run with proper isolation and error suppression
        import asyncio
        import warnings

        # Temporarily suppress ResourceWarnings and RuntimeErrors from HTTP cleanup
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', ResourceWarning)
            warnings.simplefilter('ignore', RuntimeWarning)

            # Set custom exception handler to suppress cleanup errors
            def exception_handler(loop, context):
                # Ignore "Event loop is closed" and similar cleanup errors
                if 'Event loop is closed' in str(context.get('exception', '')):
                    return
                if 'aclose' in str(context.get('exception', '')):
                    return
                # Log other exceptions normally
                loop.default_exception_handler(context)

            try:
                loop = asyncio.new_event_loop()
                loop.set_exception_handler(exception_handler)
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(agent.run(max_steps=DEFAULT_MAX_STEPS, parent_tool_instance=instance, tools=cls.get_subagent_tools()))
            except Exception as e:
                result = f'SubAgent error: {str(e)}'
            finally:
                try:
                    # Suppress any remaining tasks
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                finally:
                    asyncio.set_event_loop(None)
                    # Don't close loop explicitly to avoid cleanup issues
                    # Force garbage collection to trigger any delayed HTTP client cleanup
                    import gc

                    gc.collect()

        instance.tool_result().set_content((result or '').strip())


class CodeSearchTaskTool(Agent):
    name = 'CodeSearchTask'
    desc = CODE_SEARCH_TASK_TOOL_DESC

    @classmethod
    def get_subagent_tools(cls):
        return READ_ONLY_TOOLS


def render_agent_args(tool_call: ToolCall, is_suffix: bool = False):
    yield Text.assemble(
        (tool_call.tool_name, ColorStyle.HIGHLIGHT.bold()),
        '(',
        (tool_call.tool_args_dict.get('description', ''), ColorStyle.HIGHLIGHT.bold()),
        ')',
        ' → ',
        tool_call.tool_args_dict.get('prompt', ''),
    )


def render_agent_result(tool_msg: ToolMessage):
    tool_calls = tool_msg.get_extra_data('tool_calls')
    if tool_calls:
        for subagent_tool_call_dcit in tool_calls:
            tool_call = ToolCall(**subagent_tool_call_dcit)
            for item in tool_call.get_suffix_renderable():
                yield render_suffix(item)
        count = len(tool_calls)
        yield render_suffix(f'({count} tool use{"" if count == 1 else "s"})')
    if tool_msg.content:
        yield render_suffix(Panel.fit(render_markdown(tool_msg.content), border_style=ColorStyle.AGENT_BORDER))


register_tool_call_renderer('Task', render_agent_args)
register_tool_result_renderer('Task', render_agent_result)
register_tool_call_renderer('CodeSearchTask', render_agent_args)
register_tool_result_renderer('CodeSearchTask', render_agent_result)


async def get_main_agent(session: Session, config: ConfigModel, enable_mcp: bool = False) -> Agent:
    agent = Agent(session, config, availiable_tools=BASIC_TOOLS + [Agent, CodeSearchTaskTool])
    if enable_mcp:
        await agent.initialize_mcp()
    return agent
