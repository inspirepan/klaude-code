import json
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from codex_mini.protocol import model
from codex_mini.protocol.model import ConversationItem, TodoItem


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    work_dir: Path
    conversation_history: list[ConversationItem] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    system_prompt: str | None = None
    is_root_session: bool = True
    child_session_ids: list[str] = Field(default_factory=list)
    # Last response id: for OpenAI Responses API
    last_response_id: str | None = None
    # FileTracker: track file path -> last modification time when last read/edited
    file_tracker: dict[str, float] = Field(default_factory=dict)
    # Todo list for the session
    todos: list[TodoItem] = Field(default_factory=list)
    # Timestamps (epoch seconds)
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())

    # Internal: mapping for (de)serialization of conversation items
    _TypeMap: ClassVar[dict[str, type[BaseModel]]] = {
        # Messages
        "SystemMessageItem": model.SystemMessageItem,
        "DeveloperMessageItem": model.DeveloperMessageItem,
        "UserMessageItem": model.UserMessageItem,
        "AssistantMessageItem": model.AssistantMessageItem,
        # Reasoning/Thinking
        "ThinkingTextItem": model.ThinkingTextItem,
        "ReasoningItem": model.ReasoningItem,
        # Tools
        "ToolCallItem": model.ToolCallItem,
        "ToolResultItem": model.ToolResultItem,
        # Stream/meta (not typically persisted in history, but supported)
        "ThinkingTextDelta": model.ThinkingTextDelta,
        "AssistantMessageDelta": model.AssistantMessageDelta,
        "StartItem": model.StartItem,
        "StreamErrorItem": model.StreamErrorItem,
        "ResponseMetadataItem": model.ResponseMetadataItem,
    }

    @staticmethod
    def _project_key() -> str:
        # Derive a stable per-project key from current working directory
        return str(Path.cwd()).strip("/").replace("/", "-")

    @classmethod
    def _base_dir(cls) -> Path:
        return Path.home() / ".config" / "codex-mini" / "project" / cls._project_key()

    @classmethod
    def _sessions_dir(cls) -> Path:
        return cls._base_dir() / "sessions"

    @classmethod
    def _messages_dir(cls) -> Path:
        return cls._base_dir() / "messages"

    def _session_file(self) -> Path:
        prefix = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(self.created_at))
        return self._sessions_dir() / f"{prefix}-{self.id}.json"

    def _messages_file(self) -> Path:
        prefix = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(self.created_at))
        return self._messages_dir() / f"{prefix}-{self.id}.jsonl"

    @classmethod
    def load(cls, id: str, system_prompt: str | None = None) -> "Session":
        # Load session metadata
        sessions_dir = cls._sessions_dir()
        session_candidates = sorted(sessions_dir.glob(f"*-{id}.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not session_candidates:
            # No existing session; create a new one
            return Session(id=id, work_dir=Path.cwd(), system_prompt=system_prompt)
        session_path = session_candidates[0]

        raw = json.loads(session_path.read_text())

        # Basic fields (conversation history is loaded separately)
        work_dir_str = raw.get("work_dir", str(Path.cwd()))
        is_root_session = bool(raw.get("is_root_session", True))
        child_session_ids = list(raw.get("child_session_ids", []))
        last_response_id = raw.get("last_response_id")
        file_tracker = dict(raw.get("file_tracker", {}))
        todos: list[TodoItem] = [TodoItem(**item) for item in raw.get("todos", [])]
        created_at = float(raw.get("created_at", time.time()))
        updated_at = float(raw.get("updated_at", created_at))

        sess = Session(
            id=id,
            work_dir=Path(work_dir_str),
            system_prompt=system_prompt,
            is_root_session=is_root_session,
            child_session_ids=child_session_ids,
            last_response_id=last_response_id,
            file_tracker=file_tracker,
            todos=todos,
            created_at=created_at,
            updated_at=updated_at,
        )

        # Load conversation history from messages JSONL
        messages_dir = cls._messages_dir()
        # Expect a single messages file per session (prefixed filenames only)
        msg_candidates = sorted(messages_dir.glob(f"*-{id}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if msg_candidates:
            messages_path = msg_candidates[0]
            history: list[ConversationItem] = []
            for line in messages_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    t = obj.get("type")
                    data = obj.get("data", {})
                    cls_type = cls._TypeMap.get(t or "")
                    if cls_type is None:
                        continue
                    item = cls_type(**data)
                    # pyright: ignore[reportAssignmentType]
                    history.append(item)  # type: ignore[arg-type]
                except Exception:
                    # Best-effort load; skip malformed lines
                    continue
            sess.conversation_history = history

        return sess

    def save(self):
        # Ensure directories exist
        sessions_dir = self._sessions_dir()
        messages_dir = self._messages_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        messages_dir.mkdir(parents=True, exist_ok=True)

        # Persist session metadata (excluding conversation history)
        # Update timestamps
        if self.created_at <= 0:
            self.created_at = time.time()
        self.updated_at = time.time()
        payload = {
            "id": self.id,
            "work_dir": str(self.work_dir),
            "is_root_session": self.is_root_session,
            "child_session_ids": self.child_session_ids,
            "last_response_id": self.last_response_id,
            "file_tracker": self.file_tracker,
            "todos": [todo.model_dump() for todo in self.todos],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        self._session_file().write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def append_history(self, items: Sequence[ConversationItem]):
        # Append to in-memory history
        self.conversation_history.extend(items)

        # Incrementally persist to JSONL under messages directory
        messages_dir = self._messages_dir()
        messages_dir.mkdir(parents=True, exist_ok=True)
        mpath = self._messages_file()

        with mpath.open("a", encoding="utf-8") as f:
            for it in items:
                # Serialize with explicit type tag for reliable load
                t = it.__class__.__name__
                data = it.model_dump()
                f.write(json.dumps({"type": t, "data": data}, ensure_ascii=False))
                f.write("\n")
        # Refresh metadata timestamp after history change
        self.save()

    @classmethod
    def most_recent_session_id(cls) -> str | None:
        sessions_dir = cls._sessions_dir()
        if not sessions_dir.exists():
            return None
        latest_id: str | None = None
        latest_ts: float = -1.0
        for p in sessions_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                sid = str(data.get("id", p.stem))
                ts = float(data.get("updated_at", 0.0))
                if ts <= 0:
                    ts = p.stat().st_mtime
                if ts > latest_ts:
                    latest_ts = ts
                    latest_id = sid
            except Exception:
                continue
        return latest_id
