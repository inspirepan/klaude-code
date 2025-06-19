import json
import os
import time
import uuid
from pathlib import Path
from typing import Callable, List, Literal, Optional

from pydantic import BaseModel, Field

from .message import AIMessage, BasicMessage, SystemMessage, ToolMessage, UserMessage
from .tui import console
from .utils import sanitize_filename


class Session(BaseModel):
    """Session model for managing conversation history and metadata."""

    messages: List[BasicMessage] = Field(default_factory=list)
    # todo_list: List[Todo] = Field(default_factory=list)
    work_dir: str
    title: str = ''
    session_id: str = ''
    append_message_hook: Optional[Callable] = None

    def __init__(
        self,
        work_dir: str,
        messages: Optional[List[BasicMessage]] = None,
        append_message_hook: Optional[Callable] = None,
    ) -> None:
        super().__init__(
            work_dir=work_dir,
            messages=messages or [],
            session_id=str(uuid.uuid4()),
            title='',
            append_message_hook=append_message_hook,
        )

    def append_message(self, *msgs: BasicMessage) -> None:
        """Add messages to the session and save it."""
        self.messages.extend(msgs)
        self.save()
        if self.append_message_hook:
            self.append_message_hook(*msgs)

    def get_last_message(self, role: Literal['user', 'assistant', 'tool'] | None = None) -> Optional[BasicMessage]:
        """Get the last message with the specified role."""
        if role:
            return next((msg for msg in reversed(self.messages) if msg.role == role), None)
        return self.messages[-1] if self.messages else None

    def get_first_message(self, role: Literal['user', 'assistant', 'tool'] | None = None) -> Optional[BasicMessage]:
        """Get the first message with the specified role"""
        if role:
            return next((msg for msg in self.messages if msg.role == role), None)
        return self.messages[0] if self.messages else None

    def print_all(self):
        """Print all messages in the session"""
        for msg in self.messages:
            console.print(msg)

    def _get_session_dir(self) -> Path:
        """Get the directory path for storing session files."""
        return Path(self.work_dir) / '.klaude' / 'sessions'

    def _get_metadata_file_path(self) -> Path:
        """Get the file path for session metadata."""
        return self._get_session_dir() / f'{self.session_id}.metadata.json'

    def _get_messages_file_path(self) -> Path:
        """Get the file path for session messages."""
        first_user_msg = self.get_first_message(role='user')
        if first_user_msg:
            sanitized_title = sanitize_filename(first_user_msg.content, max_length=20)
            return self._get_session_dir() / f'{self.session_id}.messages_{sanitized_title}.json'
        else:
            return self._get_session_dir() / f'{self.session_id}.messages_untitled.json'

    def save(self) -> None:
        """Save session to local files (metadata and messages separately)"""
        # Only save sessions that have user messages (meaningful conversations)
        if not any(msg.role == 'user' for msg in self.messages):
            return

        try:
            if not self._get_session_dir().exists():
                self._get_session_dir().mkdir(parents=True)
            metadata_file = self._get_metadata_file_path()
            messages_file = self._get_messages_file_path()
            current_time = time.time()
            # Save metadata (lightweight for fast listing)
            metadata = {
                'id': self.session_id,
                'work_dir': self.work_dir,
                'title': self.title or (self.get_last_message(role='user').content[:20] if self.get_last_message(role='user') else 'Untitled'),
                'created_at': getattr(self, '_created_at', current_time),
                'updated_at': current_time,
                'message_count': len(self.messages),
                # "todo_list": [todo.model_dump() for todo in self.todo_list],
            }

            # Set created_at if not exists
            if not hasattr(self, '_created_at'):
                self._created_at = current_time

            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Save messages (heavy data)
            messages_data = {
                'session_id': self.session_id,
                'messages': [msg.model_dump() for msg in self.messages],
            }

            with open(messages_file, 'w', encoding='utf-8') as f:
                json.dump(messages_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            console.print(f'[red]Failed to save session - error: {e}[/red]')

    @classmethod
    def load(cls, session_id: str, work_dir: str = os.getcwd()) -> Optional['Session']:
        """Load session from local files"""

        try:
            # Create a temporary session to get the correct directory
            temp_session = cls(work_dir=work_dir)
            temp_session.session_id = session_id
            metadata_file = temp_session._get_metadata_file_path()
            session_dir = temp_session._get_session_dir()
            messages_files = list(session_dir.glob(f'{session_id}.messages_*.json'))
            if not messages_files:
                return None
            messages_file = messages_files[0]
            if not metadata_file.exists() or not messages_file.exists():
                return None
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            with open(messages_file, 'r', encoding='utf-8') as f:
                messages_data = json.load(f)
            messages = []
            for msg_data in messages_data.get('messages', []):
                role = msg_data.get('role')
                if role == 'system':
                    messages.append(SystemMessage(**msg_data))
                elif role == 'user':
                    messages.append(UserMessage(**msg_data))
                elif role == 'assistant':
                    messages.append(AIMessage(**msg_data))
                elif role == 'tool':
                    messages.append(ToolMessage(**msg_data))
            session = cls(work_dir=metadata['work_dir'], messages=messages)
            session.session_id = metadata['id']
            session.title = metadata.get('title', '')
            session._created_at = metadata.get('created_at')
            return session

        except Exception as e:
            console.print(f'[red]Failed to load session {session_id}: {e}[/red]')
            return None

    def fork(self) -> 'Session':
        forked_session = Session(
            work_dir=self.work_dir,
            messages=self.messages.copy(),  # Copy the messages list
            # todo_list=self.todo_list.copy(),
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
            for metadata_file in session_dir.glob('*.metadata.json'):
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    sessions.append(
                        {
                            'id': metadata['id'],
                            'title': metadata.get('title', 'Untitled'),
                            'work_dir': metadata['work_dir'],
                            'created_at': metadata.get('created_at'),
                            'updated_at': metadata.get('updated_at'),
                            'message_count': metadata.get('message_count', 0),
                        }
                    )
                except Exception as e:
                    console.print(f'[yellow]Warning: Failed to read metadata file {metadata_file}: {e}[/yellow]')
                    continue
            sessions.sort(key=lambda x: x.get('updated_at', 0), reverse=True)
            return sessions

        except Exception as e:
            console.print(f'[red]Failed to list sessions: {e}[/red]')
            return []

    @classmethod
    def get_latest_session(cls, work_dir: str = os.getcwd()) -> Optional['Session']:
        """Get the most recent session for the current working directory."""
        sessions = cls.load_session_list(work_dir)
        if not sessions:
            return None
        latest_session = sessions[0]
        return cls.load(latest_session['id'], work_dir)
