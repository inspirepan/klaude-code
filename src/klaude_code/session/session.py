import json
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field, PrivateAttr

from klaude_code.protocol import events, model, tools


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    work_dir: Path
    conversation_history: list[model.ConversationItem] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    sub_agent_state: model.SubAgentState | None = None
    # FileTracker: track file path -> last modification time when last read/edited
    file_tracker: dict[str, float] = Field(default_factory=dict)
    # Todo list for the session
    todos: list[model.TodoItem] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    # Model name used for this session
    # Used in list method SessionMetaBrief
    model_name: str | None = None
    # Timestamps (epoch seconds)
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())

    # Reminder flags
    loaded_memory: list[str] = Field(default_factory=list)
    need_todo_empty_cooldown_counter: int = Field(exclude=True, default=0)
    need_todo_not_used_cooldown_counter: int = Field(exclude=True, default=0)

    # Cached messages count (computed property)
    _messages_count_cache: int | None = PrivateAttr(default=None)

    @property
    def messages_count(self) -> int:
        """Count of user, assistant messages, and tool calls in conversation history.

        This is a cached property that is invalidated when append_history is called.
        """
        if self._messages_count_cache is None:
            self._messages_count_cache = sum(
                1
                for it in self.conversation_history
                if isinstance(it, (model.UserMessageItem, model.AssistantMessageItem, model.ToolCallItem))
            )
        return self._messages_count_cache

    def _invalidate_messages_count_cache(self) -> None:
        """Invalidate the cached messages count."""
        self._messages_count_cache = None

    # Internal: mapping for (de)serialization of conversation items
    _TypeMap: ClassVar[dict[str, type[BaseModel]]] = {
        # Messages
        "SystemMessageItem": model.SystemMessageItem,
        "DeveloperMessageItem": model.DeveloperMessageItem,
        "UserMessageItem": model.UserMessageItem,
        "AssistantMessageItem": model.AssistantMessageItem,
        # Reasoning/Thinking
        "ReasoningTextItem": model.ReasoningTextItem,
        "ReasoningEncryptedItem": model.ReasoningEncryptedItem,
        # Tools
        "ToolCallItem": model.ToolCallItem,
        "ToolResultItem": model.ToolResultItem,
        # Stream/meta (not typically persisted in history, but supported)
        "AssistantMessageDelta": model.AssistantMessageDelta,
        "StartItem": model.StartItem,
        "StreamErrorItem": model.StreamErrorItem,
        "TaskMetadataItem": model.TaskMetadataItem,
        "InterruptItem": model.InterruptItem,
    }

    @staticmethod
    def _project_key() -> str:
        # Derive a stable per-project key from current working directory
        return str(Path.cwd()).strip("/").replace("/", "-")

    @classmethod
    def _base_dir(cls) -> Path:
        return Path.home() / ".klaude" / "projects" / cls._project_key()

    @classmethod
    def _sessions_dir(cls) -> Path:
        return cls._base_dir() / "sessions"

    @classmethod
    def _messages_dir(cls) -> Path:
        return cls._base_dir() / "messages"

    @classmethod
    def _exports_dir(cls) -> Path:
        return cls._base_dir() / "exports"

    def _session_file(self) -> Path:
        prefix = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(self.created_at))
        return self._sessions_dir() / f"{prefix}-{self.id}.json"

    def _messages_file(self) -> Path:
        prefix = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(self.created_at))
        return self._messages_dir() / f"{prefix}-{self.id}.jsonl"

    @classmethod
    def create(cls, id: str | None = None) -> "Session":
        """Create a new session without checking for existing files."""
        return Session(id=id or uuid.uuid4().hex, work_dir=Path.cwd())

    @classmethod
    def load(cls, id: str) -> "Session":
        """Load an existing session or create a new one if not found."""
        # Load session metadata
        sessions_dir = cls._sessions_dir()
        session_candidates = sorted(
            sessions_dir.glob(f"*-{id}.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not session_candidates:
            # No existing session; create a new one
            return Session(id=id, work_dir=Path.cwd())
        session_path = session_candidates[0]

        raw = json.loads(session_path.read_text())

        # Basic fields (conversation history is loaded separately)
        work_dir_str = raw.get("work_dir", str(Path.cwd()))

        sub_agent_state_raw = raw.get("sub_agent_state")
        sub_agent_state = model.SubAgentState(**sub_agent_state_raw) if sub_agent_state_raw else None
        file_tracker = dict(raw.get("file_tracker", {}))
        todos: list[model.TodoItem] = [model.TodoItem(**item) for item in raw.get("todos", [])]
        loaded_memory = list(raw.get("loaded_memory", []))
        created_at = float(raw.get("created_at", time.time()))
        updated_at = float(raw.get("updated_at", created_at))
        model_name = raw.get("model_name")

        sess = Session(
            id=id,
            work_dir=Path(work_dir_str),
            sub_agent_state=sub_agent_state,
            file_tracker=file_tracker,
            todos=todos,
            loaded_memory=loaded_memory,
            created_at=created_at,
            updated_at=updated_at,
            model_name=model_name,
        )

        # Load conversation history from messages JSONL
        messages_dir = cls._messages_dir()
        # Expect a single messages file per session (prefixed filenames only)
        msg_candidates = sorted(
            messages_dir.glob(f"*-{id}.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if msg_candidates:
            messages_path = msg_candidates[0]
            history: list[model.ConversationItem] = []
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
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Best-effort load; skip malformed lines
                    continue
            sess.conversation_history = history
            # messages_count is now a computed property, no need to set it

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
            "sub_agent_state": self.sub_agent_state.model_dump() if self.sub_agent_state else None,
            "file_tracker": self.file_tracker,
            "todos": [todo.model_dump() for todo in self.todos],
            "loaded_memory": self.loaded_memory,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages_count": self.messages_count,
            "model_name": self.model_name,
        }
        self._session_file().write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    def append_history(self, items: Sequence[model.ConversationItem]):
        # Append to in-memory history
        self.conversation_history.extend(items)
        # Invalidate messages count cache
        self._invalidate_messages_count_cache()

        # Incrementally persist to JSONL under messages directory
        messages_dir = self._messages_dir()
        messages_dir.mkdir(parents=True, exist_ok=True)
        mpath = self._messages_file()

        with mpath.open("a", encoding="utf-8") as f:
            for it in items:
                # Serialize with explicit type tag for reliable load
                t = it.__class__.__name__
                data = it.model_dump(mode="json")
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
                # Filter out sub-agent sessions
                if data.get("sub_agent_state", None) is not None:
                    continue
                sid = str(data.get("id", p.stem))
                ts = float(data.get("updated_at", 0.0))
                if ts <= 0:
                    ts = p.stat().st_mtime
                if ts > latest_ts:
                    latest_ts = ts
                    latest_id = sid
            except (json.JSONDecodeError, KeyError, TypeError, OSError):
                continue
        return latest_id

    def need_turn_start(self, prev_item: model.ConversationItem | None, item: model.ConversationItem) -> bool:
        # Emit TurnStartEvent when a new turn starts to show an empty line in replay history
        if not isinstance(
            item,
            model.ReasoningEncryptedItem | model.ReasoningTextItem | model.AssistantMessageItem | model.ToolCallItem,
        ):
            return False
        if prev_item is None:
            return True
        return isinstance(
            prev_item,
            model.UserMessageItem | model.ToolResultItem | model.DeveloperMessageItem,
        )

    def get_history_item(self) -> Iterable[events.HistoryItemEvent]:
        seen_sub_agent_sessions: set[str] = set()
        prev_item: model.ConversationItem | None = None
        last_assistant_content: str = ""
        report_back_result: str | None = None
        yield events.TaskStartEvent(session_id=self.id, sub_agent_state=self.sub_agent_state)
        for it in self.conversation_history:
            if self.need_turn_start(prev_item, it):
                yield events.TurnStartEvent(
                    session_id=self.id,
                )
            match it:
                case model.AssistantMessageItem() as am:
                    content = am.content or ""
                    last_assistant_content = content
                    yield events.AssistantMessageEvent(
                        content=content,
                        response_id=am.response_id,
                        session_id=self.id,
                    )
                case model.ToolCallItem() as tc:
                    if tc.name == tools.REPORT_BACK:
                        report_back_result = tc.arguments
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
                        task_metadata=tr.task_metadata,
                    )
                    yield from self._iter_sub_agent_history(tr, seen_sub_agent_sessions)
                case model.UserMessageItem() as um:
                    yield events.UserMessageEvent(
                        content=um.content or "",
                        session_id=self.id,
                    )
                case model.ReasoningTextItem() as ri:
                    yield events.ThinkingEvent(
                        content=ri.content,
                        session_id=self.id,
                    )
                case model.TaskMetadataItem() as mt:
                    yield events.TaskMetadataEvent(
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
                case model.StreamErrorItem() as se:
                    yield events.ErrorEvent(
                        error_message=se.error,
                        can_retry=False,
                    )
                case _:
                    continue
            prev_item = it

        has_structured_output = report_back_result is not None
        task_result = report_back_result if has_structured_output else last_assistant_content
        yield events.TaskFinishEvent(
            session_id=self.id,
            task_result=task_result,
            has_structured_output=has_structured_output,
        )

    def _iter_sub_agent_history(
        self, tool_result: model.ToolResultItem, seen_sub_agent_sessions: set[str]
    ) -> Iterable[events.HistoryItemEvent]:
        """Replay sub-agent session history when a tool result references it.

        Sub-agent tool results embed a SessionIdUIExtra containing the child session ID.
        When present, we load that session and yield its history events so replay/export
        can show the full sub-agent transcript instead of only the summarized tool output.
        """
        ui_extra = tool_result.ui_extra
        if not isinstance(ui_extra, model.SessionIdUIExtra):
            return

        session_id = ui_extra.session_id
        if not session_id or session_id == self.id:
            return
        if session_id in seen_sub_agent_sessions:
            return

        seen_sub_agent_sessions.add(session_id)

        try:
            sub_session = Session.load(session_id)
        except Exception:
            return

        yield from sub_session.get_history_item()

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
    def list_sessions(cls) -> list[SessionMetaBrief]:
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
                    messages_dir.glob(f"*-{session_id}.jsonl"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
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
                                if (
                                    isinstance(part, dict) and part.get("type") == "text"  # pyright: ignore[reportUnknownMemberType]
                                ):
                                    text = part.get("text", "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
                                    if isinstance(text, str):
                                        text_parts.append(text)
                            return " ".join(text_parts) if text_parts else None
                        return None
            except (json.JSONDecodeError, KeyError, TypeError, OSError):
                return None
            return None

        items: list[Session.SessionMetaBrief] = []
        for p in sessions_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                # Skip unreadable files
                continue
            # Filter out sub-agent sessions
            if data.get("sub_agent_state", None) is not None:
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

    @classmethod
    def clean_small_sessions(cls, min_messages: int = 5) -> int:
        """Remove sessions with fewer than min_messages messages.

        Returns the number of sessions deleted.
        """
        sessions = cls.list_sessions()
        deleted_count = 0

        for session_meta in sessions:
            # Skip sessions with unknown message count
            if session_meta.messages_count < 0:
                continue
            if session_meta.messages_count < min_messages:
                cls._delete_session_files(session_meta.id, session_meta.created_at)
                deleted_count += 1

        return deleted_count

    @classmethod
    def clean_all_sessions(cls) -> int:
        """Remove all sessions for the current project.

        Returns the number of sessions deleted.
        """
        sessions = cls.list_sessions()
        deleted_count = 0

        for session_meta in sessions:
            cls._delete_session_files(session_meta.id, session_meta.created_at)
            deleted_count += 1

        return deleted_count

    @classmethod
    def _delete_session_files(cls, session_id: str, created_at: float) -> None:
        """Delete session and messages files for a given session."""
        sessions_dir = cls._sessions_dir()
        messages_dir = cls._messages_dir()

        # Delete session file
        prefix = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(created_at))
        session_file = sessions_dir / f"{prefix}-{session_id}.json"
        if session_file.exists():
            session_file.unlink()

        # Delete messages file
        messages_file = messages_dir / f"{prefix}-{session_id}.jsonl"
        if messages_file.exists():
            messages_file.unlink()
