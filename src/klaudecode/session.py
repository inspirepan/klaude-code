import json
import os
import time
import uuid
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .message import BasicMessage, SystemMessage, UserMessage, AIMessage, ToolMessage
from .tui import console


class Session(BaseModel):
    messages: List[BasicMessage] = Field(default_factory=list)
    # todo_list: List[Todo] = Field(default_factory=list)
    work_dir: str
    title: str = ""
    session_id: str = ""

    def __init__(
        self, work_dir: str, messages: Optional[List[BasicMessage]] = None
    ) -> "Session":
        # Initialize with proper Pydantic model initialization
        super().__init__(
            work_dir=work_dir,
            messages=messages or [],
            session_id=str(uuid.uuid4()),
            title="",
        )

    def append_message(self, msg: BasicMessage):
        self.messages.append(msg)
        self.save()

    def get_last_message(
        self, role: Literal["user", "assistant", "tool"] | None = None
    ) -> BasicMessage:
        if role:
            return next((msg for msg in reversed(self.messages) if msg.role == role), None)
        return self.messages[-1] if self.messages else None

    def get_first_message(
        self, role: Literal["user", "assistant", "tool"] | None = None
    ) -> BasicMessage:
        """Get the first message with the specified role"""
        if role:
            return next((msg for msg in self.messages if msg.role == role), None)
        return self.messages[0] if self.messages else None

    def _get_session_dir(self) -> Path:
        return Path(self.work_dir) / ".klaude" / "sessions"

    def _get_metadata_file_path(self) -> Path:
        return self._get_session_dir() / f"{self.session_id}_metadata.json"

    def _get_messages_file_path(self) -> Path:
        return self._get_session_dir() / f"{self.session_id}_messages.json"

    def save(self) -> None:
        """Save session to local files (metadata and messages separately)"""
        # Only save sessions that have user messages (meaningful conversations)
        if not any(msg.role == "user" for msg in self.messages):
            return

        try:
            if not self._get_session_dir().exists():
                self._get_session_dir().mkdir(parents=True)
            metadata_file = self._get_metadata_file_path()
            messages_file = self._get_messages_file_path()
            current_time = time.time()
            # Save metadata (lightweight for fast listing)
            metadata = {
                "id": self.session_id,
                "work_dir": self.work_dir,
                "title": self.title or self.get_last_message(role="user").content[:20],
                "created_at": getattr(self, "_created_at", current_time),
                "updated_at": current_time,
                "message_count": len(self.messages),
                # "todo_list": [todo.model_dump() for todo in self.todo_list],
            }

            # Set created_at if not exists
            if not hasattr(self, "_created_at"):
                self._created_at = current_time

            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            # Save messages (heavy data)
            messages_data = {
                "session_id": self.session_id,
                "messages": [msg.model_dump() for msg in self.messages],
            }

            with open(messages_file, "w", encoding="utf-8") as f:
                json.dump(messages_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            console.print(f"[red]Failed to save session - error: {e}[/red]")

    @classmethod
    def load(cls, session_id: str, work_dir: str = os.getcwd()) -> Optional["Session"]:
        """Load session from local files"""

        try:
            # Create a temporary session to get the correct directory
            temp_session = cls(work_dir=work_dir)
            temp_session.session_id = session_id
            metadata_file = temp_session._get_metadata_file_path()
            messages_file = temp_session._get_messages_file_path()
            if not metadata_file.exists() or not messages_file.exists():
                return None
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            with open(messages_file, "r", encoding="utf-8") as f:
                messages_data = json.load(f)
            messages = []
            for msg_data in messages_data.get("messages", []):
                role = msg_data.get("role")
                if role == "system":
                    messages.append(SystemMessage(**msg_data))
                elif role == "user":
                    messages.append(UserMessage(**msg_data))
                elif role == "assistant":
                    messages.append(AIMessage(**msg_data))
                elif role == "tool":
                    messages.append(ToolMessage(**msg_data))
            session = cls(
                work_dir=metadata["work_dir"], messages=messages
            )
            session.id = metadata["id"]
            session.title = metadata.get("title", "")
            session._created_at = metadata.get("created_at")
            return session

        except Exception as e:
            console.print(f"[red]Failed to load session {session_id}: {e}[/red]")
            return None

    @classmethod
    def load_session_list(cls, work_dir: str = os.getcwd()) -> list[dict]:
        try:
            session_dir = cls(work_dir=work_dir)._get_session_dir()
            if not session_dir.exists():
                return []
            sessions = []
            for metadata_file in session_dir.glob("*_meta.json"):
                try:
                    with open(metadata_file, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                    sessions.append(
                        {
                            "id": metadata["id"],
                            "title": metadata.get("title", "Untitled"),
                            "work_dir": metadata["work_dir"],
                            "created_at": metadata.get("created_at"),
                            "updated_at": metadata.get("updated_at"),
                            "message_count": metadata.get("message_count", 0),
                        }
                    )
                except Exception as e:
                    console.print(
                        f"[yellow]Warning: Failed to read metadata file {metadata_file}: {e}[/yellow]"
                    )
                    continue
            sessions.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
            return sessions

        except Exception as e:
            console.print(f"[red]Failed to list sessions: {e}[/red]")
            return []

    @classmethod
    def get_latest_session(cls, work_dir: str = os.getcwd()) -> Optional["Session"]:
        """Get the most recent session for the current working directory"""
        sessions = cls.list_sessions(work_dir)
        if not sessions:
            return None
        # Return the most recent session (first in the list)
        latest_session = sessions[0]
        return cls.load(latest_session["id"], work_dir)
