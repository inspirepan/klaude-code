import threading
import time
import uuid
import weakref
from pathlib import Path
from typing import Callable, List, Literal, Optional

from pydantic import BaseModel, Field, field_serializer

from ..llm import LLMManager
from ..message import BasicMessage
from ..tools.todo import TodoList
from ..utils.file_utils import FileTracker
from .message_history import MessageHistory
from .session_operations import SessionOperations
from .session_storage import SessionStorage


class Session(BaseModel):
    """Session model for managing conversation history and metadata."""

    messages: MessageHistory = Field(default_factory=MessageHistory)
    todo_list: TodoList = Field(default_factory=TodoList)
    file_tracker: FileTracker = Field(default_factory=FileTracker)
    work_dir: Path
    source: Literal['user', 'subagent', 'clear', 'compact'] = 'user'
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = Field(default_factory=time.time)
    append_message_hook: Optional[Callable] = None
    title_msg: str = ''
    _initial_message_count: int = 0
    _incremental_message_count: int = 0

    def __init__(self, **data):
        # Handle messages parameter - convert list to MessageHistory if needed
        if 'messages' in data and isinstance(data['messages'], list):
            data['messages'] = MessageHistory(messages=data['messages'])

        super().__init__(**data)
        self._hook_weakref: Optional[weakref.ReferenceType] = None
        self._hook_lock = threading.RLock()

        # Initialize message count tracking
        self._initial_message_count = len(self.messages.messages)
        self._incremental_message_count = 0

    @field_serializer('work_dir')
    def serialize_work_dir(self, work_dir: Path) -> str:
        return str(work_dir)

    def append_message(self, *msgs: BasicMessage) -> None:
        """Add messages to the session."""
        self.messages.append_message(*msgs)
        # Track incremental message count
        self._incremental_message_count += len(msgs)

        # Update title_msg when the first new message is a user message
        if self._incremental_message_count == 1 and len(msgs) == 1:
            msg = msgs[0]
            self.reset_create_at()
            if hasattr(msg, 'role') and msg.role == 'user' and hasattr(msg, 'user_raw_input'):
                # Append new user message to existing title
                content = msg.user_raw_input or msg.content
                truncated_content = content[:50] if content else ''
                # Only add ellipsis if content was actually truncated
                if content and len(content) > 50:
                    truncated_content += '...'

                old_title_msg = self.title_msg
                new_title_msg = truncated_content
                if old_title_msg:
                    new_title_msg = f'{old_title_msg}.{new_title_msg}'
                if not new_title_msg:
                    new_title_msg = 'UNTITLED'
                self.title_msg = new_title_msg

        with self._hook_lock:
            if self._hook_weakref:
                try:
                    # Get the actual callback from weakref
                    hook = self._hook_weakref()
                    if hook is not None:
                        hook(*msgs)
                    else:
                        # Callback was garbage collected, clear the reference
                        self._hook_weakref = None
                        self.append_message_hook = None
                except Exception as e:
                    # Log the exception but don't let it break the message appending
                    import logging

                    logging.warning(f'Exception in append_message_hook: {e}')

    def set_append_message_hook(self, hook: Optional[Callable] = None) -> None:
        """Set the append message hook with automatic weakref conversion."""
        with self._hook_lock:
            if hook is not None:
                self.append_message_hook = hook
                self._hook_weakref = weakref.ref(hook)
            else:
                self.append_message_hook = None
                self._hook_weakref = None

    def save(self) -> None:
        """Save session to local files only if there are meaningful changes."""
        # Only save if we have incremental messages beyond just loading the session
        if self._incremental_message_count > 0:
            SessionStorage.save(self)

    def reset_create_at(self):
        current_time = time.time()
        self.created_at = current_time

    def _create_session_from_template(self, filter_removed: bool = False, source: Optional[Literal['user', 'subagent', 'clear', 'compact']] = None) -> 'Session':
        """Create a new session based on this session's template with optional filtering and source."""
        if filter_removed:
            messages = [msg for msg in self.messages.messages if not msg.removed]
        else:
            messages = self.messages.messages

        kwargs = {
            'work_dir': self.work_dir,
            'messages': messages,
            'todo_list': self.todo_list,
            'file_tracker': self.file_tracker,
            'title_msg': self.title_msg,
        }

        if source is not None:
            kwargs['source'] = source

        return Session(**kwargs)

    def create_new_session(self) -> 'Session':
        return self._create_session_from_template()

    def clear_conversation_history(self):
        """Clear conversation history by creating a new session for real cleanup"""
        SessionOperations.clear_conversation_history(self)

    async def compact_conversation_history(self, instructions: str = '', show_status: bool = True, llm_manager: Optional[LLMManager] = None):
        """Compact conversation history using LLM to summarize."""
        await SessionOperations.compact_conversation_history(self, instructions, show_status, llm_manager)

    async def analyze_conversation_for_command(self, llm_manager: Optional[LLMManager] = None) -> Optional[dict]:
        """Analyze conversation to extract command pattern."""
        return await SessionOperations.analyze_conversation_for_command(self, llm_manager)

    @classmethod
    def load(cls, session_id: str, work_dir: Path = Path.cwd()) -> Optional['Session']:
        """Load session from local files"""
        return SessionStorage.load(session_id, work_dir)

    @classmethod
    def load_session_list(cls, work_dir: Path = Path.cwd()) -> List[dict]:
        """Load a list of session metadata from the specified directory."""
        return SessionStorage.load_session_list(work_dir)

    @classmethod
    def get_latest_session(cls, work_dir: Path = Path.cwd()) -> Optional['Session']:
        """Get the most recent session for the current working directory."""
        return SessionStorage.get_latest_session(work_dir)
