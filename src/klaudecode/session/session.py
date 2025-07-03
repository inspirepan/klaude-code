import time
import uuid
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
    session_id: str = ''
    append_message_hook: Optional[Callable] = None
    title_msg: str = ''

    @field_serializer('work_dir')
    def serialize_work_dir(self, work_dir: Path) -> str:
        return str(work_dir)

    def __init__(
        self,
        work_dir: Path,
        messages: Optional[List[BasicMessage]] = None,
        append_message_hook: Optional[Callable] = None,
        todo_list: Optional[TodoList] = None,
        file_tracker: Optional[FileTracker] = None,
        source: Literal['user', 'subagent', 'clear', 'compact'] = 'user',
    ) -> None:
        super().__init__(
            work_dir=work_dir,
            messages=MessageHistory(messages=messages or []),
            session_id=str(uuid.uuid4()),
            append_message_hook=append_message_hook,
            todo_list=todo_list or TodoList(),
            file_tracker=file_tracker or FileTracker(),
            source=source,
        )

    def append_message(self, *msgs: BasicMessage) -> None:
        """Add messages to the session."""
        self.messages.append_message(*msgs)
        if self.append_message_hook:
            self.append_message_hook(*msgs)

    def save(self) -> None:
        """Save session to local files."""
        SessionStorage.save(self)

    def reset_create_at(self):
        current_time = time.time()
        self._created_at = current_time

    def create_new_session(self) -> 'Session':
        new_session = Session(
            work_dir=self.work_dir,
            messages=self.messages.messages,
            todo_list=self.todo_list,
            file_tracker=self.file_tracker,
        )
        return new_session

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
