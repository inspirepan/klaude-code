import json
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from codex_mini.protocol import events, model
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
    todos: list[TodoItem] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    # Messages count
    messages_count: int = Field(default=0)
    # Model name used for this session
    # Used in list method SessionMetaBrief
    model_name: str | None = None
    # Timestamps (epoch seconds)
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())
    loaded_memory: list[str] = Field(default_factory=list)
    need_todo_empty_cooldown_counter: int = Field(exclude=True, default=0)
    need_todo_not_used_cooldown_counter: int = Field(exclude=True, default=0)

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
        "InterruptItem": model.InterruptItem,
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
    def load(cls, id: str) -> "Session":
        # Load session metadata
        sessions_dir = cls._sessions_dir()
        session_candidates = sorted(sessions_dir.glob(f"*-{id}.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not session_candidates:
            # No existing session; create a new one
            return Session(id=id, work_dir=Path.cwd())
        session_path = session_candidates[0]

        raw = json.loads(session_path.read_text())

        # Basic fields (conversation history is loaded separately)
        work_dir_str = raw.get("work_dir", str(Path.cwd()))
        is_root_session = bool(raw.get("is_root_session", True))
        child_session_ids = list(raw.get("child_session_ids", []))
        last_response_id = raw.get("last_response_id")
        file_tracker = dict(raw.get("file_tracker", {}))
        todos: list[TodoItem] = [TodoItem(**item) for item in raw.get("todos", [])]
        loaded_memory = list(raw.get("loaded_memory", []))
        created_at = float(raw.get("created_at", time.time()))
        updated_at = float(raw.get("updated_at", created_at))
        messages_count = int(raw.get("messages_count", 0))
        model_name = raw.get("model_name")

        sess = Session(
            id=id,
            work_dir=Path(work_dir_str),
            is_root_session=is_root_session,
            child_session_ids=child_session_ids,
            last_response_id=last_response_id,
            file_tracker=file_tracker,
            todos=todos,
            loaded_memory=loaded_memory,
            created_at=created_at,
            updated_at=updated_at,
            messages_count=messages_count,
            model_name=model_name,
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
            # Update messages count based on loaded history
            sess.messages_count = len(history)

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
            "loaded_memory": self.loaded_memory,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages_count": self.messages_count,
            "model_name": self.model_name,
        }
        self._session_file().write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def append_history(self, items: Sequence[ConversationItem]):
        # Append to in-memory history
        self.conversation_history.extend(items)
        # Update messages count
        self.messages_count = len(self.conversation_history)

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

    def get_history_item(self) -> Iterable[events.HistoryItemEvent]:
        for it in self.conversation_history:
            match it:
                case model.AssistantMessageItem() as am:
                    content = am.content or ""
                    yield events.AssistantMessageEvent(
                        content=content,
                        response_id=am.response_id,
                        session_id=self.id,
                        annotations=am.annotations,
                    )

                case model.ToolCallItem() as tc:
                    yield events.ToolCallEvent(
                        tool_call_id=tc.call_id,
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        response_id=tc.response_id,
                        session_id=self.id,
                    )
                case model.ToolResultItem() as tr:
                    yield events.ToolResultEvent(
                        tool_call_id=tr.call_id,
                        tool_name=str(tr.tool_name),
                        result=tr.output or "",
                        ui_extra=tr.ui_extra,
                        session_id=self.id,
                        status=tr.status,
                    )

                case model.UserMessageItem() as um:
                    yield events.UserMessageEvent(
                        content=um.content or "",
                        session_id=self.id,
                    )
                case model.ReasoningItem() as ri:
                    yield events.ThinkingEvent(
                        content=ri.content or ("\n".join(ri.summary or [])),
                        session_id=self.id,
                    )
                case model.ResponseMetadataItem() as mt:
                    yield events.ResponseMetadataEvent(
                        session_id=self.id,
                        metadata=mt,
                    )
                case model.InterruptItem():
                    yield events.InterruptEvent(
                        session_id=self.id,
                    )
                case model.DeveloperMessageItem() as dm:
                    yield events.DeveloperMessageEvent(
                        session_id=self.id,
                        item=dm,
                    )
                case _:
                    continue

    class SessionMetaBrief(BaseModel):
        id: str
        created_at: float
        updated_at: float
        work_dir: str
        path: str
        first_user_message: str | None = None
        messages_count: int = -1  # -1 indicates N/A
        model_name: str | None = None

    @classmethod
    def list(cls) -> list[SessionMetaBrief]:
        """List all sessions for the current project.

        Returns a list of dicts with keys: id, created_at, updated_at, work_dir, path.
        Sorted by updated_at descending.
        """
        sessions_dir = cls._sessions_dir()
        if not sessions_dir.exists():
            return []

        def _get_first_user_message(session_id: str, created_at: float) -> str | None:
            """Get the first user message from the session's jsonl file."""
            messages_dir = cls._messages_dir()
            if not messages_dir.exists():
                return None

            # Find the messages file for this session
            prefix = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(created_at))
            msg_file = messages_dir / f"{prefix}-{session_id}.jsonl"

            if not msg_file.exists():
                # Try to find by pattern if exact file doesn't exist
                msg_candidates = sorted(
                    messages_dir.glob(f"*-{session_id}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
                )
                if not msg_candidates:
                    return None
                msg_file = msg_candidates[0]

            try:
                for line in msg_file.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    if obj.get("type") == "UserMessageItem":
                        data = obj.get("data", {})
                        content = data.get("content", "")
                        if isinstance(content, str):
                            return content
                        elif isinstance(content, list) and content:
                            # Handle structured content - extract text
                            text_parts: list[str] = []
                            for part in content:  # pyright: ignore[reportUnknownVariableType]
                                if isinstance(part, dict) and part.get("type") == "text":  # pyright: ignore[reportUnknownMemberType]
                                    text = part.get("text", "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
                                    if isinstance(text, str):
                                        text_parts.append(text)
                            return " ".join(text_parts) if text_parts else None
                        return None
            except Exception:
                return None
            return None

        items: list[Session.SessionMetaBrief] = []
        for p in sessions_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text())
            except Exception:
                # Skip unreadable files
                continue
            sid = str(data.get("id", p.stem))
            created = float(data.get("created_at", p.stat().st_mtime))
            updated = float(data.get("updated_at", p.stat().st_mtime))
            work_dir = str(data.get("work_dir", ""))

            # Get first user message
            first_user_message = _get_first_user_message(sid, created)

            # Get messages count from session data, no fallback
            messages_count = int(data.get("messages_count", -1))  # -1 indicates N/A

            # Get model name from session data
            model_name = data.get("model_name")

            items.append(
                Session.SessionMetaBrief(
                    id=sid,
                    created_at=created,
                    updated_at=updated,
                    work_dir=work_dir,
                    path=str(p),
                    first_user_message=first_user_message,
                    messages_count=messages_count,
                    model_name=model_name,
                )
            )
        # Sort by updated_at desc
        items.sort(key=lambda d: d.updated_at, reverse=True)
        return items
