import asyncio
from typing import Callable, List, Optional

from anthropic import AnthropicError
from openai import OpenAIError
from rich.text import Text

from ..message import INTERRUPTED_MSG, AIMessage, SpecialUserMessageTypeEnum, ToolCall, ToolMessage, UserMessage
from ..prompt.plan_mode import APPROVE_MSG, PLAN_MODE_REMINDER, REJECT_MSG
from ..prompt.reminder import FILE_DELETED_EXTERNAL_REMINDER, FILE_MODIFIED_EXTERNAL_REMINDER
from ..tool import Tool, ToolHandler
from ..tools import ExitPlanModeTool
from ..tools.read import execute_read
from ..tui import ColorStyle, console, render_message, render_suffix
from ..user_input import user_select
from ..utils.exception import format_exception
from .state import AgentState

TOKEN_WARNING_THRESHOLD = 0.75
COMPACT_THRESHOLD = 0.8
DEFAULT_MAX_STEPS = 100


class AgentExecutor(Tool):
    """
    AgentExecutor contains the core execution logic for running LLM conversations and tool handling.
    It focuses purely on the execution loop without handling user input or interface concerns.
    """

    def __init__(self, agent_state: AgentState):
        self.agent_state = agent_state
        self.tool_handler = ToolHandler(self.agent_state, show_live=agent_state.print_switch)

    async def run(self, max_steps: int = DEFAULT_MAX_STEPS, check_cancel: Callable[[], bool] = None, tools: Optional[List[Tool]] = None):
        try:
            return await self._execute_run_loop(max_steps, check_cancel, tools)
        except (OpenAIError, AnthropicError) as e:
            return self._handle_llm_error(e)
        except (KeyboardInterrupt, asyncio.CancelledError):
            return self._handle_interruption()
        except Exception as e:
            return self._handle_general_error(e)

    async def _execute_run_loop(self, max_steps: int, check_cancel: Callable[[], bool], tools: Optional[List[Tool]]):
        usage_token_count = 0
        for _ in range(max_steps):
            if check_cancel and check_cancel():
                return INTERRUPTED_MSG

            await self._prepare_iteration(tools, usage_token_count)

            ai_msg, usage_token_count = await self._process_llm_call(tools)

            result = await self._handle_ai_response(ai_msg)
            if result is not None:
                return result

        return self._handle_max_steps_reached(max_steps)

    async def _prepare_iteration(self, tools: Optional[List[Tool]], usage_token_count: int):
        await self._auto_compact_conversation(tools, usage_token_count)

        self._handle_plan_mode_reminder()

        self._handle_file_external_modified_reminder()

        self.agent_state.session.save()

    async def _process_llm_call(self, tools: Optional[List[Tool]]):
        ai_msg = await self.agent_state.llm_manager.call(
            msgs=self.agent_state.session.messages,
            tools=tools,
            show_status=self.agent_state.print_switch,
        )

        usage_token_count = 0
        if ai_msg.usage:
            usage_token_count = (ai_msg.usage.prompt_tokens or 0) + (ai_msg.usage.completion_tokens or 0)

        self.agent_state.usage.update(ai_msg)
        self.agent_state.session.append_message(ai_msg)

        return ai_msg, usage_token_count

    async def _handle_ai_response(self, ai_msg: AIMessage):
        if ai_msg.finish_reason == 'stop':
            last_ai_msg = self.agent_state.session.messages.get_last_message(role='assistant', filter_empty=True)
            self.agent_state.session.save()
            return last_ai_msg.content if last_ai_msg else ''

        if ai_msg.finish_reason == 'tool_calls' and len(ai_msg.tool_calls) > 0:
            if not await self._handle_exit_plan_mode(ai_msg.tool_calls):
                return REJECT_MSG

            await self.tool_handler.handle(ai_msg)

        return None

    def _handle_llm_error(self, e: Exception):
        error_msg = f'LLM error: {format_exception(e)}'
        console.print(render_suffix(error_msg, style=ColorStyle.ERROR))
        return error_msg

    def _handle_general_error(self, e: Exception):
        error_msg = f'Error: {format_exception(e, show_traceback=True)}'
        console.print(render_suffix(error_msg, style=ColorStyle.ERROR))
        return error_msg

    def _handle_max_steps_reached(self, max_steps: int):
        max_step_msg = f'Max steps {max_steps} reached'
        if self.agent_state.print_switch:
            console.print(render_message(max_step_msg, mark_style=ColorStyle.INFO))
        return max_step_msg

    def _handle_plan_mode_reminder(self):
        if not self.agent_state.plan_mode_activated:
            return
        last_msg = self.agent_state.session.messages.get_last_message(filter_empty=True)
        if last_msg and isinstance(last_msg, (UserMessage, ToolMessage)):
            last_msg.append_post_system_reminder(PLAN_MODE_REMINDER)

    def _handle_file_external_modified_reminder(self):
        modified_files = self.agent_state.session.file_tracker.get_all_modified()
        if not modified_files:
            return

        last_msg = self.agent_state.session.messages.get_last_message(filter_empty=True)
        if not last_msg or not isinstance(last_msg, (UserMessage, ToolMessage)):
            return

        for file_path in modified_files:
            try:
                result = execute_read(file_path, tracker=self.agent_state.session.file_tracker)
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
        console.print()
        console.print(exit_plan_call)

        if not self.agent_state.print_switch:
            # For subagent, skip asking user for confirmation
            approved = True
        else:
            # Ask user for confirmation
            options = ['Yes', 'No, keep planning']
            selection = await user_select(options, 'Would you like to proceed?')
            approved = selection == 0

        if approved:
            self.agent_state.plan_mode_activated = False

        tool_msg = ToolMessage(tool_call_id=exit_plan_call.id, tool_call_cache=exit_plan_call, content=APPROVE_MSG if approved else REJECT_MSG)
        tool_msg.set_extra_data('approved', approved)
        console.print(*tool_msg.get_suffix_renderable())
        self.agent_state.session.append_message(tool_msg)

        return approved

    def _handle_interruption(self):
        # Clean up any live displays
        if hasattr(console.console, '_live') and console.console._live:
            try:
                console.console._live.stop()
            except Exception as e:
                console.print(f'Error stopping live display: {format_exception(e)}')
                pass

        # Add interrupted message
        user_msg = UserMessage(content=INTERRUPTED_MSG, user_msg_type=SpecialUserMessageTypeEnum.INTERRUPTED.value)
        console.print()
        console.print(user_msg)
        self.agent_state.session.append_message(user_msg)
        return INTERRUPTED_MSG

    async def _auto_compact_conversation(self, tools: Optional[List[Tool]] = None, usage_token_count: int = 0):
        """Check token count and compact conversation history if necessary"""
        if not self.agent_state.config or not self.agent_state.config.context_window_threshold:
            return
        total_tokens = 0
        if usage_token_count > 0:
            total_tokens = usage_token_count
        else:
            total_tokens = sum(msg.tokens for msg in self.agent_state.session.messages if msg)
            if tools:
                total_tokens += sum(tool.tokens() for tool in tools)
            else:
                total_tokens += sum(tool.tokens() for tool in self.agent_state.all_tools)
        total_tokens += self.agent_state.config.max_tokens.value
        if total_tokens > self.agent_state.config.context_window_threshold.value * TOKEN_WARNING_THRESHOLD:
            percentage = (total_tokens / (self.agent_state.config.context_window_threshold.value * COMPACT_THRESHOLD)) * 100
            console.print(
                Text(
                    f'Notice: token usage {percentage:.1f}% of compact threshold ({total_tokens}/{int(self.agent_state.config.context_window_threshold.value * COMPACT_THRESHOLD)})',
                    style=ColorStyle.WARNING,
                )
            )
        if total_tokens > self.agent_state.config.context_window_threshold.value * COMPACT_THRESHOLD:
            await self.agent_state.session.compact_conversation_history(show_status=self.agent_state.print_switch, llm_manager=self.agent_state.llm_manager)
