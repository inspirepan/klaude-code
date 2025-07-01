import asyncio
import json
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_serializer
from rich.text import Text

from .llm import LLMManager
from .message import AIMessage, BasicMessage, SpecialUserMessageTypeEnum, SystemMessage, ToolMessage, UserMessage
from .prompt.commands import ANALYZE_FOR_COMMAND_PROMPT, ANALYZE_FOR_COMMAND_SYSTEM_PROMPT, COMACT_SYSTEM_PROMPT, COMPACT_COMMAND, COMPACT_MSG_PREFIX
from .tools.command_pattern_result import CommandPatternResultTool
from .tools.todo import TodoList
from .tui import ColorStyle, console
from .utils.file_utils import FileTracker
from .utils.str_utils import sanitize_filename


class MessageStorageStatus(str, Enum):
    """Status of message storage in JSONL file, used exclusively for incremental updates."""

    NEW = 'new'  # Message not yet stored
    STORED = 'stored'  # Message stored in file


class MessageStorageState(BaseModel):
    """State tracking for message storage in JSONL format."""

    status: MessageStorageStatus = MessageStorageStatus.NEW
    line_number: Optional[int] = None  # Line number in JSONL file (0-based)
    file_path: Optional[str] = None  # Path to JSONL file


class MessageHistory(BaseModel):
    messages: List[BasicMessage] = Field(default_factory=list)
    storage_states: Dict[int, MessageStorageState] = Field(default_factory=dict, exclude=True)

    def append_message(self, *msgs: BasicMessage) -> None:
        start_index = len(self.messages)
        self.messages.extend(msgs)
        # Mark new messages as NEW status
        for i, _ in enumerate(msgs, start=start_index):
            self.storage_states[i] = MessageStorageState(status=MessageStorageStatus.NEW)

    def get_storage_state(self, index: int) -> MessageStorageState:
        """Get storage state for a message."""
        return self.storage_states.get(index, MessageStorageState())

    def set_storage_state(self, index: int, state: MessageStorageState) -> None:
        """Set storage state for a message."""
        self.storage_states[index] = state

    def get_unsaved_messages(self) -> List[tuple[int, BasicMessage]]:
        """Get all messages that need to be saved (NEW)."""
        return [(i, msg) for i, msg in enumerate(self.messages) if self.storage_states.get(i, MessageStorageState()).status == MessageStorageStatus.NEW]

    def reset_storage_states(self) -> None:
        for i in range(len(self.messages)):
            self.storage_states[i] = MessageStorageState(status=MessageStorageStatus.NEW, line_number=i + 1, file_path=None)

    def get_last_message(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> Optional[BasicMessage]:
        return next((msg for msg in reversed(self.messages) if (not role or msg.role == role) and (not filter_empty or msg)), None)

    def get_first_message(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> Optional[BasicMessage]:
        return next((msg for msg in self.messages if (not role or msg.role == role) and (not filter_empty or msg)), None)

    def get_role_messages(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> List[BasicMessage]:
        return [msg for msg in self.messages if (not role or msg.role == role) and (not filter_empty or msg)]

    def print_all_message(self):
        from .tui import console

        for msg in self.messages:
            if msg.role == 'system':
                continue
            console.print(msg)
            console.print('')

    def copy(self):
        return self.messages.copy()

    def extend(self, msgs):
        self.messages.extend(msgs)

    def __len__(self) -> int:
        return len(self.messages)

    def __iter__(self):
        return iter(self.messages)

    def __getitem__(self, index):
        return self.messages[index]


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

    def _get_session_dir(self) -> Path:
        """Get the directory path for storing session files."""
        return Path(self.work_dir) / '.klaude' / 'sessions'

    def _get_formatted_filename_prefix(self) -> str:
        """Generate formatted filename prefix with datetime and title."""
        created_at = getattr(self, '_created_at', time.time())
        dt = datetime.fromtimestamp(created_at)
        datetime_str = dt.strftime('%Y_%m%d_%H%M%S')
        title = sanitize_filename(self.title_msg, max_length=40)
        if self.source == 'subagent':
            source_str = '.SUBAGENT'
        elif self.source == 'clear':
            source_str = '.CLEAR'
        elif self.source == 'compact':
            source_str = '.COMPACT'
        else:
            source_str = ''
        return f'{datetime_str}{source_str}.{title}'

    def _get_metadata_file_path(self) -> Path:
        """Get the file path for session metadata."""
        prefix = self._get_formatted_filename_prefix()
        return self._get_session_dir() / f'{prefix}.metadata.{self.session_id}.json'

    def _get_messages_file_path(self) -> Path:
        """Get the file path for session messages."""
        prefix = self._get_formatted_filename_prefix()
        return self._get_session_dir() / f'{prefix}.messages.{self.session_id}.jsonl'

    def save(self) -> None:
        """Save session to local files (metadata and messages separately)"""
        # Only save sessions that have user messages (meaningful conversations)
        if not any(msg.role == 'user' for msg in self.messages):
            return

        try:
            if not self._get_session_dir().exists():
                self._get_session_dir().mkdir(parents=True)

            if not self.title_msg:
                first_user_msg: Optional[UserMessage] = self.messages.get_first_message(role='user')
                if first_user_msg is not None:
                    self.title_msg = first_user_msg.user_raw_input or first_user_msg.content
                else:
                    self.title_msg = 'untitled'

            metadata_file = self._get_metadata_file_path()
            messages_file = self._get_messages_file_path()
            current_time = time.time()

            # Set created_at if not exists
            if not hasattr(self, '_created_at'):
                self._created_at = current_time

            # Save metadata (lightweight for fast listing)
            metadata = {
                'id': self.session_id,
                'work_dir': str(self.work_dir),
                'created_at': getattr(self, '_created_at', current_time),
                'updated_at': current_time,
                'message_count': len(self.messages),
                'todo_list': self.todo_list.model_dump(),
                'file_tracker': self.file_tracker.model_dump(),
                'source': self.source,
                'title_msg': self.title_msg,
            }

            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Save messages using JSONL format with incremental updates
            self._save_messages_jsonl(messages_file)

        except Exception as e:
            console.print(Text(f'Failed to save session - error: {e}', style=ColorStyle.ERROR.value))

    def _save_messages_jsonl(self, messages_file: Path) -> None:
        """Save messages to JSONL file with incremental updates."""
        unsaved_messages = self.messages.get_unsaved_messages()

        if not unsaved_messages:
            return

        # Create file if it doesn't exist
        if not messages_file.exists():
            with open(messages_file, 'w', encoding='utf-8') as f:
                # Write session header
                header = {'session_id': self.session_id, 'version': '1.0'}
                f.write(json.dumps(header, ensure_ascii=False) + '\n')

            # All messages are new, write them all
            with open(messages_file, 'a', encoding='utf-8') as f:
                for i, msg in enumerate(self.messages):
                    msg_data = msg.model_dump(exclude_none=True)
                    f.write(json.dumps(msg_data, ensure_ascii=False) + '\n')
                    # Update storage state
                    state = MessageStorageState(
                        status=MessageStorageStatus.STORED,
                        line_number=i + 1,  # +1 for header line
                        file_path=str(messages_file),
                    )
                    self.messages.set_storage_state(i, state)
        else:
            # Read existing file to get line count
            with open(messages_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Handle new messages (append)
            if unsaved_messages:
                with open(messages_file, 'a', encoding='utf-8') as f:
                    for i, msg in unsaved_messages:
                        msg_data = msg.model_dump(exclude_none=True)
                        f.write(json.dumps(msg_data, ensure_ascii=False) + '\n')
                        # Update storage state
                        state = MessageStorageState(status=MessageStorageStatus.STORED, line_number=len(lines), file_path=str(messages_file))
                        self.messages.set_storage_state(i, state)
                        lines.append('')  # Track line count

    @classmethod
    def load(cls, session_id: str, work_dir: Path = Path.cwd()) -> Optional['Session']:
        """Load session from local files"""

        try:
            session_dir = cls(work_dir=work_dir)._get_session_dir()
            metadata_files = list(session_dir.glob(f'*.metadata.{session_id}.json'))
            messages_files = list(session_dir.glob(f'*.messages.{session_id}.jsonl'))

            if not metadata_files or not messages_files:
                return None

            metadata_file = metadata_files[0]
            messages_file = messages_files[0]

            if not metadata_file.exists() or not messages_file.exists():
                return None

            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            # Load messages from JSONL file
            messages = []
            tool_calls_dict = {}

            with open(messages_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Skip header line (first line contains session info)
            for line_num, line in enumerate(lines[1:], start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    msg_data = json.loads(line)
                    role = msg_data.get('role')

                    if role == 'system':
                        messages.append(SystemMessage(**msg_data))
                    elif role == 'user':
                        messages.append(UserMessage(**msg_data))
                    elif role == 'assistant':
                        ai_msg = AIMessage(**msg_data)
                        if ai_msg.tool_calls:
                            for tool_call_id, tool_call in ai_msg.tool_calls.items():
                                tool_calls_dict[tool_call_id] = tool_call
                        messages.append(ai_msg)
                    elif role == 'tool':
                        tool_call_id = msg_data.get('tool_call_id')
                        if tool_call_id and tool_call_id in tool_calls_dict:
                            msg_data['tool_call_cache'] = tool_calls_dict[tool_call_id]
                        else:
                            raise ValueError(f'Tool call {tool_call_id} not found')
                        messages.append(ToolMessage(**msg_data))
                except json.JSONDecodeError as e:
                    console.print(Text(f'Warning: Failed to parse message line {line_num}: {e}', style=ColorStyle.WARNING.value))
                    continue

            todo_list_data = metadata.get('todo_list', [])
            if isinstance(todo_list_data, list):
                todo_list = TodoList(root=todo_list_data)
            else:
                todo_list = TodoList()

            file_tracker_data = metadata.get('file_tracker', {})
            if file_tracker_data:
                file_tracker = FileTracker(**file_tracker_data)
            else:
                file_tracker = FileTracker()

            session = cls(work_dir=Path(metadata['work_dir']), messages=messages, todo_list=todo_list, file_tracker=file_tracker)
            session.session_id = metadata['id']
            session._created_at = metadata.get('created_at')
            session.title_msg = metadata.get('title_msg', '')

            # Initialize storage states for loaded messages
            for i, msg in enumerate(messages):
                state = MessageStorageState(
                    status=MessageStorageStatus.STORED,
                    line_number=i + 1,  # +1 for header line
                    file_path=str(messages_file),
                )
                session.messages.set_storage_state(i, state)

            return session

        except Exception as e:
            console.print(Text(f'Failed to load session {session_id}: {e}', style=ColorStyle.ERROR.value))
            return None

    def create_new_session(self) -> 'Session':
        new_session = Session(
            work_dir=self.work_dir,
            messages=self.messages.messages,
            todo_list=self.todo_list,
            file_tracker=self.file_tracker,
        )
        return new_session

    def _create_cleared_session(self, source: Literal['clear', 'compact']) -> 'Session':
        """Create a new session containing only non-removed messages"""
        # Filter out messages marked as removed
        active_messages = [msg for msg in self.messages.messages if not msg.removed]

        # Create new session
        new_session = Session(
            work_dir=self.work_dir,
            messages=active_messages,
            todo_list=self.todo_list,
            file_tracker=self.file_tracker,
            source=source,
        )

        return new_session

    @classmethod
    def load_session_list(cls, work_dir: Path = Path.cwd()) -> List[dict]:
        """Load a list of session metadata from the specified directory."""
        try:
            session_dir = cls(work_dir=work_dir)._get_session_dir()
            if not session_dir.exists():
                return []
            sessions = []
            for metadata_file in session_dir.glob('*.metadata.*.json'):
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    if metadata.get('source', 'user') == 'subagent':
                        continue
                    sessions.append(
                        {
                            'id': metadata['id'],
                            'work_dir': metadata['work_dir'],
                            'created_at': metadata.get('created_at'),
                            'updated_at': metadata.get('updated_at'),
                            'message_count': metadata.get('message_count', 0),
                            'source': metadata.get('source', 'user'),
                            'title_msg': metadata.get('title_msg', ''),
                        }
                    )
                except Exception as e:
                    console.print(Text(f'Warning: Failed to read metadata file {metadata_file}: {e}', style=ColorStyle.WARNING.value))
                    continue
            sessions.sort(key=lambda x: x.get('updated_at', 0), reverse=True)
            return sessions

        except Exception as e:
            console.print(Text(f'Failed to list sessions: {e}', style=ColorStyle.ERROR.value))
            return []

    @classmethod
    def get_latest_session(cls, work_dir: Path = Path.cwd()) -> Optional['Session']:
        """Get the most recent session for the current working directory."""
        sessions = cls.load_session_list(work_dir)
        if not sessions:
            return None
        latest_session = sessions[0]
        return cls.load(latest_session['id'], work_dir)

    def clear_conversation_history(self):
        """Clear conversation history by creating a new session for real cleanup"""
        # First mark non-system messages as removed (for filtering)
        for msg in self.messages:
            if msg.role == 'system':
                continue
            msg.removed = True

        # Save old session
        self.save()

        # Create cleared session
        cleared_session = self._create_cleared_session('clear')

        # Replace current session attributes with new session data
        self.session_id = cleared_session.session_id
        self.messages = cleared_session.messages
        self.source = cleared_session.source

        # Reset message storage states since this is a brand new session
        self.messages.reset_storage_states()

    async def compact_conversation_history(self, instructions: str = '', show_status: bool = True, llm_manager: Optional[LLMManager] = None):
        non_sys_msgs = [msg for msg in self.messages if msg.role != 'system'].copy()
        additional_instructions = '\nAdditional Instructions:\n' + instructions if instructions else ''
        # TODO: Maybe add some tool call results? Check CC
        CompactMessageList = MessageHistory(
            messages=[SystemMessage(content=COMACT_SYSTEM_PROMPT)] + non_sys_msgs + [UserMessage(content=COMPACT_COMMAND + additional_instructions)]
        )

        try:
            if llm_manager:
                ai_msg = await llm_manager.call(msgs=CompactMessageList, show_status=show_status, status_text='Compacting...')
            else:
                raise RuntimeError('LLM manager not initialized')

            # First mark non-system messages as removed (for filtering)
            for msg in self.messages:
                if msg.role == 'system':
                    continue
                msg.removed = True

            # Create compact result message
            user_msg = UserMessage(content=COMPACT_MSG_PREFIX + ai_msg.content, user_msg_type=SpecialUserMessageTypeEnum.COMPACT_RESULT.value)
            console.print(user_msg)

            # Append compact result to old session
            self.append_message(user_msg)

            # Create compact session
            compacted_session = self._create_cleared_session('compact')

            # Replace current session attributes with new session data
            self.session_id = compacted_session.session_id
            self.messages = compacted_session.messages
            self.source = compacted_session.source

            # Reset message storage states since this is a brand new session
            self.messages.reset_storage_states()

        except (KeyboardInterrupt, asyncio.CancelledError):
            pass

    async def analyze_conversation_for_command(self, llm_manager: Optional[LLMManager] = None) -> Optional[dict]:
        non_sys_msgs = [msg for msg in self.messages if msg.role != 'system'].copy()

        analyze_message_list = MessageHistory(
            messages=[SystemMessage(content=ANALYZE_FOR_COMMAND_SYSTEM_PROMPT)] + non_sys_msgs + [UserMessage(content=ANALYZE_FOR_COMMAND_PROMPT)]
        )

        try:
            if llm_manager:
                ai_msg = await llm_manager.call(msgs=analyze_message_list, show_status=True, status_text='Patterning...', tools=[CommandPatternResultTool])

                if ai_msg.tool_calls:
                    for tool_call in ai_msg.tool_calls.values():
                        if tool_call.tool_name == CommandPatternResultTool.get_name():
                            return tool_call.tool_args_dict

                console.print('No tool call found in analysis response', style=ColorStyle.ERROR.value)
                return None
            else:
                raise RuntimeError('LLM manager not initialized')

        except (KeyboardInterrupt, asyncio.CancelledError):
            return None
