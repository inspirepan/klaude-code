import asyncio
from typing import TYPE_CHECKING, Optional

from ..llm import LLMManager
from ..message import SpecialUserMessageTypeEnum, SystemMessage, UserMessage
from ..prompt.commands import ANALYZE_COMMAND_PATTERN_PROMPT, ANALYZE_COMMAND_PATTERN_SYSTEM_PROMPT, COMACT_SYSTEM_PROMPT, COMPACT_COMMAND, COMPACT_MSG_PREFIX
from ..tools.command_pattern_result import CommandPatternResultTool
from ..tui import ColorStyle, console
from .message_history import MessageHistory

if TYPE_CHECKING:
    from .session import Session


class SessionOperations:
    """Handles session operations like clear and compact."""

    @staticmethod
    def clear_conversation_history(session: 'Session') -> None:
        """Clear conversation history by creating a new session for real cleanup"""
        # First mark non-system messages as removed (for filtering)
        for msg in session.messages:
            if msg.role == 'system':
                continue
            msg.removed = True

        # Save old session
        from .session_storage import SessionStorage

        SessionStorage.save(session)

        # Create cleared session
        cleared_session = session._create_session_from_template(filter_removed=True, source='clear')

        # Replace current session attributes with new session data
        session.session_id = cleared_session.session_id
        session.messages = cleared_session.messages
        session.source = cleared_session.source
        session.reset_create_at()

        # Reset message storage states since this is a brand new session
        session.messages.reset_storage_states()

    @staticmethod
    async def compact_conversation_history(session: 'Session', instructions: str = '', show_status: bool = True, llm_manager: Optional[LLMManager] = None) -> None:
        """Compact conversation history using LLM to summarize."""
        non_sys_msgs = [msg for msg in session.messages if msg.role != 'system'].copy()
        additional_instructions = '\nAdditional Instructions:\n' + instructions if instructions else ''
        CompactMessageList = MessageHistory(
            messages=[SystemMessage(content=COMACT_SYSTEM_PROMPT)] + non_sys_msgs + [UserMessage(content=COMPACT_COMMAND + additional_instructions)]
        )

        try:
            if llm_manager:
                ai_msg = await llm_manager.call(msgs=CompactMessageList, show_status=show_status, show_result=False, status_text='Compacting')
            else:
                raise RuntimeError('LLM manager not initialized')

            # First mark non-system messages as removed (for filtering)
            for msg in session.messages:
                if msg.role == 'system':
                    continue
                msg.removed = True

            # Create compact result message
            user_msg = UserMessage(content=COMPACT_MSG_PREFIX + ai_msg.content, user_msg_type=SpecialUserMessageTypeEnum.COMPACT_RESULT.value)
            console.print(user_msg)

            # Append compact result to old session
            session.append_message(user_msg)

            # Create compact session
            compacted_session = session._create_session_from_template(filter_removed=True, source='compact')

            # Replace current session attributes with new session data
            session.session_id = compacted_session.session_id
            session.messages = compacted_session.messages
            session.source = compacted_session.source

            # Reset message storage states since this is a brand new session
            session.messages.reset_storage_states()

        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

    @staticmethod
    async def analyze_conversation_for_command(session: 'Session', llm_manager: Optional[LLMManager] = None) -> Optional[dict]:
        """Analyze conversation to extract command pattern."""
        non_sys_msgs = [msg for msg in session.messages if msg.role != 'system'].copy()

        analyze_message_list = MessageHistory(
            messages=[SystemMessage(content=ANALYZE_COMMAND_PATTERN_SYSTEM_PROMPT)] + non_sys_msgs + [UserMessage(content=ANALYZE_COMMAND_PATTERN_PROMPT)]
        )

        try:
            if llm_manager:
                ai_msg = await llm_manager.call(msgs=analyze_message_list, show_status=True, show_result=False, status_text='Patterning', tools=[CommandPatternResultTool])

                if ai_msg.tool_calls:
                    for tool_call in ai_msg.tool_calls.values():
                        if tool_call.tool_name == CommandPatternResultTool.get_name():
                            return tool_call.tool_args_dict

                console.print('No tool call found in analysis response', style=ColorStyle.ERROR)
                return None
            else:
                raise RuntimeError('LLM manager not initialized')

        except (KeyboardInterrupt, asyncio.CancelledError):
            return None
