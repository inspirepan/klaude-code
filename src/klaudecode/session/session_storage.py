import json
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from rich.text import Text

from ..message import AIMessage, SystemMessage, ToolMessage, UserMessage
from ..tui import ColorStyle, console
from ..utils.exception import format_exception
from ..utils.str_utils import sanitize_filename
from .message_history import MessageStorageState, MessageStorageStatus

if TYPE_CHECKING:
    from .session import Session


class SessionStorage:
    """Handles session persistence to disk."""

    @staticmethod
    def get_session_dir(work_dir: Path) -> Path:
        """Get the directory path for storing session files."""
        return Path(work_dir) / '.klaude' / 'sessions'

    @staticmethod
    def get_formatted_filename_prefix(session: 'Session') -> str:
        """Generate formatted filename prefix with datetime and title."""
        dt = datetime.fromtimestamp(session.created_at)
        datetime_str = dt.strftime('%Y_%m%d_%H%M%S')
        title = sanitize_filename(session.title_msg, max_length=40)
        if session.source == 'subagent':
            source_str = '.SUBAGENT'
        elif session.source == 'clear':
            source_str = '.CLEAR'
        elif session.source == 'compact':
            source_str = '.COMPACT'
        else:
            source_str = ''
        return f'{datetime_str}{source_str}.{title}'

    @classmethod
    def get_metadata_file_path(cls, session: 'Session') -> Path:
        """Get the file path for session metadata."""
        prefix = cls.get_formatted_filename_prefix(session)
        return cls.get_session_dir(session.work_dir) / f'{prefix}.metadata.{session.session_id}.json'

    @classmethod
    def get_messages_file_path(cls, session: 'Session') -> Path:
        """Get the file path for session messages."""
        prefix = cls.get_formatted_filename_prefix(session)
        return cls.get_session_dir(session.work_dir) / f'{prefix}.messages.{session.session_id}.jsonl'

    @classmethod
    def save(cls, session: 'Session') -> None:
        """Save session to local files (metadata and messages separately)"""
        # Only save sessions that have user messages (meaningful conversations)
        if not any(msg.role == 'user' for msg in session.messages):
            return

        try:
            session_dir = cls.get_session_dir(session.work_dir)
            if not session_dir.exists():
                session_dir.mkdir(parents=True)

            metadata_file = cls.get_metadata_file_path(session)
            messages_file = cls.get_messages_file_path(session)
            current_time = time.time()

            # Save metadata (lightweight for fast listing)
            metadata = {
                'id': session.session_id,
                'work_dir': str(session.work_dir),
                'created_at': session.created_at,
                'updated_at': current_time,
                'message_count': len(session.messages),
                'todo_list': session.todo_list.model_dump(),
                'file_tracker': session.file_tracker.model_dump(),
                'source': session.source,
                'title_msg': session.title_msg or 'UNTITLED',
            }

            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Save messages using JSONL format with incremental updates
            cls._save_messages_jsonl(session, messages_file)

        except Exception as e:
            console.print(Text(f'Failed to save session - error: {format_exception(e)}', style=ColorStyle.ERROR))

    @classmethod
    def _save_messages_jsonl(cls, session: 'Session', messages_file: Path) -> None:
        """Save messages to JSONL file with incremental updates."""
        unsaved_messages = session.messages.get_unsaved_messages()

        if not unsaved_messages:
            return

        # Create file if it doesn't exist
        if not messages_file.exists():
            with open(messages_file, 'w', encoding='utf-8') as f:
                # Write session header
                header = {'session_id': session.session_id, 'version': '1.0'}
                f.write(json.dumps(header, ensure_ascii=False) + '\n')

            # All messages are new, write them all
            with open(messages_file, 'a', encoding='utf-8') as f:
                for i, msg in enumerate(session.messages):
                    msg_data = msg.model_dump(exclude_none=True)
                    f.write(json.dumps(msg_data, ensure_ascii=False) + '\n')
                    # Update storage state
                    state = MessageStorageState(
                        status=MessageStorageStatus.STORED,
                        line_number=i + 1,  # +1 for header line
                        file_path=str(messages_file),
                    )
                    session.messages.set_storage_state(i, state)
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
                        session.messages.set_storage_state(i, state)
                        lines.append('')  # Track line count

    @classmethod
    def load(cls, session_id: str, work_dir: Path = Path.cwd()) -> Optional['Session']:
        """Load session from local files"""
        from ..tools.todo import TodoList
        from ..utils.file_utils import FileTracker
        from .session import Session

        try:
            session_dir = cls.get_session_dir(work_dir)
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
                    console.print(Text(f'Warning: Failed to parse message line {line_num}: {format_exception(e)}', style=ColorStyle.WARNING))
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

            session = Session(work_dir=Path(metadata['work_dir']), messages=messages, todo_list=todo_list, file_tracker=file_tracker)
            session.session_id = metadata['id']
            session.created_at = metadata.get('created_at', session.created_at)
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
            console.print(Text(f'Failed to load session {session_id}: {format_exception(e)}', style=ColorStyle.ERROR))
            return None

    @classmethod
    def load_session_list(cls, work_dir: Path = Path.cwd()) -> List[dict]:
        """Load a list of session metadata from the specified directory."""
        try:
            session_dir = cls.get_session_dir(work_dir)
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
                            'title_msg': metadata.get('title_msg', 'UNTITLED'),
                        }
                    )
                except Exception as e:
                    console.print(Text(f'Warning: Failed to read metadata file {metadata_file}: {format_exception(e)}', style=ColorStyle.WARNING))
                    continue
            sessions.sort(key=lambda x: x.get('updated_at', 0), reverse=True)
            return sessions

        except Exception as e:
            console.print(Text(f'Failed to list sessions: {format_exception(e)}', style=ColorStyle.ERROR))
            return []

    @classmethod
    def get_latest_session(cls, work_dir: Path = Path.cwd()) -> Optional['Session']:
        """Get the most recent session for the current working directory."""
        sessions = cls.load_session_list(work_dir)
        if not sessions:
            return None
        latest_session = sessions[0]
        return cls.load(latest_session['id'], work_dir)
