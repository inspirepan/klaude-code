import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from rich.text import Text

from .llm import AgentLLM
from .message import AIMessage, BasicMessage, SpecialUserMessageTypeEnum, SystemMessage, ToolMessage, UserMessage
from .prompt.commands import COMACT_SYSTEM_PROMPT, COMPACT_COMMAND, COMPACT_MSG_PREFIX
from .tools.todo import TodoList
from .tui import ColorStyle, console
from .utils import sanitize_filename


class MessageStorageStatus(str, Enum):
    """Status of message storage in JSONL file."""

    NEW = 'new'  # Message not yet stored
    STORED = 'stored'  # Message stored in file
    MODIFIED = 'modified'  # Message modified after storage


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
        for i, msg in enumerate(msgs, start=start_index):
            self.storage_states[i] = MessageStorageState(status=MessageStorageStatus.NEW)

    def mark_message_modified(self, index: int) -> None:
        """Mark a message as modified for incremental update."""
        if index in self.storage_states and self.storage_states[index].status == MessageStorageStatus.STORED:
            self.storage_states[index].status = MessageStorageStatus.MODIFIED

    def get_storage_state(self, index: int) -> MessageStorageState:
        """Get storage state for a message."""
        return self.storage_states.get(index, MessageStorageState())

    def set_storage_state(self, index: int, state: MessageStorageState) -> None:
        """Set storage state for a message."""
        self.storage_states[index] = state

    def get_unsaved_messages(self) -> List[tuple[int, BasicMessage]]:
        """Get all messages that need to be saved (NEW or MODIFIED)."""
        return [
            (i, msg)
            for i, msg in enumerate(self.messages)
            if self.storage_states.get(i, MessageStorageState()).status in (MessageStorageStatus.NEW, MessageStorageStatus.MODIFIED)
        ]

    def get_last_message(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> Optional[BasicMessage]:
        return next((msg for msg in reversed(self.messages) if (not role or msg.role == role) and (not filter_empty or msg)), None)

    def get_first_message(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> Optional[BasicMessage]:
        return next((msg for msg in self.messages if (not role or msg.role == role) and (not filter_empty or msg)), None)

    def get_role_messages(self, role: Literal['user', 'assistant', 'tool'] | None = None, filter_empty: bool = False) -> List[BasicMessage]:
        return [msg for msg in self.messages if (not role or msg.role == role) and (not filter_empty or msg)]

    def print_all_message(self):
        from .tui import console

        for msg in self.messages:
            console.print(msg)

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
    work_dir: str
    source: Literal['user', 'subagent'] = 'user'
    session_id: str = ''
    append_message_hook: Optional[Callable] = None
    title_msg: str = ''

    def __init__(
        self,
        work_dir: str,
        messages: Optional[List[BasicMessage]] = None,
        append_message_hook: Optional[Callable] = None,
        todo_list: Optional[TodoList] = None,
        source: Literal['user', 'subagent'] = 'user',
    ) -> None:
        super().__init__(
            work_dir=work_dir,
            messages=MessageHistory(messages=messages or []),
            session_id=str(uuid.uuid4()),
            append_message_hook=append_message_hook,
            todo_list=todo_list or TodoList(),
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
        return f'{datetime_str}{".SUBAGENT" if self.source == "subagent" else ""}.{title}'

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
                'work_dir': self.work_dir,
                'created_at': getattr(self, '_created_at', current_time),
                'updated_at': current_time,
                'message_count': len(self.messages),
                'todo_list': self.todo_list.model_dump(),
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
            new_messages = [(i, msg) for i, msg in unsaved_messages if self.messages.get_storage_state(i).status == MessageStorageStatus.NEW]

            if new_messages:
                with open(messages_file, 'a', encoding='utf-8') as f:
                    for i, msg in new_messages:
                        msg_data = msg.model_dump(exclude_none=True)
                        f.write(json.dumps(msg_data, ensure_ascii=False) + '\n')
                        # Update storage state
                        state = MessageStorageState(status=MessageStorageStatus.STORED, line_number=len(lines), file_path=str(messages_file))
                        self.messages.set_storage_state(i, state)
                        lines.append('')  # Track line count

            # Handle modified messages (update in place)
            modified_messages = [(i, msg) for i, msg in unsaved_messages if self.messages.get_storage_state(i).status == MessageStorageStatus.MODIFIED]

            if modified_messages:
                # Read all lines
                with open(messages_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                # Update modified lines
                for i, msg in modified_messages:
                    state = self.messages.get_storage_state(i)
                    if state.line_number is not None and state.line_number < len(lines):
                        msg_data = msg.model_dump(exclude_none=True)
                        lines[state.line_number] = json.dumps(msg_data, ensure_ascii=False) + '\n'
                        # Mark as stored
                        state.status = MessageStorageStatus.STORED
                        self.messages.set_storage_state(i, state)

                # Write back all lines
                with open(messages_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines)

    @classmethod
    def load(cls, session_id: str, work_dir: str = os.getcwd()) -> Optional['Session']:
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

            session = cls(work_dir=metadata['work_dir'], messages=messages, todo_list=todo_list)
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

    def fork(self) -> 'Session':
        forked_session = Session(
            work_dir=self.work_dir,
            messages=self.messages.copy(),  # Copy the messages list
            todo_list=self.todo_list.model_copy(),
        )
        return forked_session

    @classmethod
    def load_session_list(cls, work_dir: str = os.getcwd()) -> List[dict]:
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
    def get_latest_session(cls, work_dir: str = os.getcwd()) -> Optional['Session']:
        """Get the most recent session for the current working directory."""
        sessions = cls.load_session_list(work_dir)
        if not sessions:
            return None
        latest_session = sessions[0]
        return cls.load(latest_session['id'], work_dir)

    def clear_conversation_history(self):
        for msg in self.messages:
            if msg.role == 'system':
                continue
            msg.removed = True

    async def compact_conversation_history(self, instructions: str = '', show_status: bool = True):
        non_sys_msgs = [msg for msg in self.messages if msg.role != 'system'].copy()
        additional_instructions = '\nAdditional Instructions:\n' + instructions if instructions else ''
        # TODO: Maybe add some tool call results? Check CC
        CompactMessageList = MessageHistory(
            messages=[SystemMessage(content=COMACT_SYSTEM_PROMPT)] + non_sys_msgs + [UserMessage(content=COMPACT_COMMAND + additional_instructions)]
        )

        try:
            ai_msg = await AgentLLM.call(msgs=CompactMessageList, show_status=show_status, status_text='Compacting...')

            self.clear_conversation_history()
            user_msg = UserMessage(content=COMPACT_MSG_PREFIX + ai_msg.content, user_msg_type=SpecialUserMessageTypeEnum.COMPACT_RESULT.value)
            console.print(user_msg)
            self.append_message(user_msg)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
