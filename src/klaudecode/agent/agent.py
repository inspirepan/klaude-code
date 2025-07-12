import asyncio

from rich.text import Text

from ..config import ConfigModel
from ..message import ToolMessage, UserMessage
from ..prompt.reminder import EMPTY_TODO_REMINDER, get_context_reminder
from ..session import Session
from ..tools import BASIC_TOOLS, TodoWriteTool
from ..tui import ColorStyle, console, render_dot_status
from ..user_input import InputSession, UserInputHandler
from ..utils.exception import format_exception
from ..utils.file_utils import cleanup_all_backups
from .executor import AgentExecutor
from .state import AgentState

DEFAULT_MAX_STEPS = 100
QUIT_COMMAND = ['quit', 'exit']


class Agent:
    """
    Agent serves as the main entry point for agent interactions.
    It handles chat_interactive and headless_run workflows.
    """

    def __init__(self, agent_state: AgentState):
        self.agent_state = agent_state
        self.agent_executor = AgentExecutor(agent_state)
        self.input_session = InputSession(agent_state.session.work_dir)
        self.user_input_handler = UserInputHandler(self.agent_state, self.input_session)

        # Initialize custom commands
        try:
            from ..user_command import custom_command_manager

            custom_command_manager.discover_and_register_commands(agent_state.session.work_dir)
        except Exception as e:
            if agent_state.print_switch:
                console.print(f'Warning: Failed to load custom commands: {format_exception(e, show_traceback=True)}', style=ColorStyle.WARNING)

    async def chat_interactive(self, initial_message: str = None):
        self.agent_state.initialize_llm()
        self.agent_state.session.messages.print_all_message()  # For continue and resume scene.

        # If resuming a session, this is not the agent's first run
        agent_run_first_time = self.agent_state.session.messages.get_last_message('user', filter_empty=True) is None
        try:
            while True:
                if not self.agent_state.plan_mode_activated:
                    self.input_session.reset_normal_mode()

                if agent_run_first_time and initial_message:
                    user_input_text = initial_message
                else:
                    user_input_text = await self.input_session.prompt_async()

                if user_input_text.strip().lower() in QUIT_COMMAND:
                    break

                need_agent_run = await self.user_input_handler.handle(user_input_text, print_msg=bool(initial_message))
                if need_agent_run:
                    if agent_run_first_time:
                        self._handle_claudemd_reminder()
                        self._handle_empty_todo_reminder()
                    agent_run_first_time = False
                    await self.agent_executor.run(max_steps=DEFAULT_MAX_STEPS, tools=self.agent_state.all_tools)
                else:
                    self.agent_state.session.save()
        finally:
            self.agent_state.session.save()
            # Clean up MCP resources
            if self.agent_state.mcp_manager:
                await self.agent_state.mcp_manager.shutdown()
            # Clean up backup files
            cleanup_all_backups()

    async def _headless_run_with_status_display(self):
        """Run agent executor with real-time status display"""
        status = render_dot_status(Text('Running', style=ColorStyle.STATUS), padding_line=False)
        status.start()
        running = True

        async def update_status():
            while running:
                tool_msg_count = sum(1 for msg in self.agent_state.session.messages if msg.role == 'tool')
                status.update(
                    description=Text.assemble(
                        Text.from_markup(f'([bold]{tool_msg_count}[/bold] tool uses) '),
                    ),
                )
                await asyncio.sleep(0.1)

        update_task = asyncio.create_task(update_status())
        try:
            result = await self.agent_executor.run(tools=self.agent_state.all_tools, max_steps=DEFAULT_MAX_STEPS)
            return result
        finally:
            running = False
            status.stop()
            update_task.cancel()
            try:
                await update_task
            except asyncio.CancelledError:
                pass

    async def headless_run(self, user_input_text: str):
        self.agent_state.initialize_llm()

        try:
            need_agent_run = await self.user_input_handler.handle(user_input_text, print_msg=False)
            if not need_agent_run:
                return

            self.agent_state.print_switch = False
            self.agent_executor.tool_handler.show_live = False
            self._handle_claudemd_reminder()
            self._handle_empty_todo_reminder()

            result = await self._headless_run_with_status_display()
            console.print(result)
        finally:
            self.agent_state.session.save()
            # Clean up MCP resources
            if self.agent_state.mcp_manager:
                await self.agent_state.mcp_manager.shutdown()
            # Clean up backup files
            cleanup_all_backups()

    def _handle_claudemd_reminder(self):
        reminder = get_context_reminder(self.agent_state.session.work_dir)
        last_user_msg = self.agent_state.session.messages.get_last_message(role='user')
        if last_user_msg and isinstance(last_user_msg, UserMessage):
            last_user_msg.append_pre_system_reminder(reminder)

    def _handle_empty_todo_reminder(self):
        if TodoWriteTool in self.agent_state.available_tools:
            last_msg = self.agent_state.session.messages.get_last_message(filter_empty=True)
            if last_msg and isinstance(last_msg, (UserMessage, ToolMessage)):
                last_msg.append_post_system_reminder(EMPTY_TODO_REMINDER)


async def get_main_agent(session: Session, config: ConfigModel, enable_mcp: bool = False) -> Agent:
    from ..tools.task import TaskTool

    state = AgentState(session, config, available_tools=[TaskTool] + BASIC_TOOLS)
    if enable_mcp:
        await state.initialize_mcp()
    return Agent(state)
