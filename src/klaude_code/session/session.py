from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field, PrivateAttr, ValidationError

from klaude_code.protocol import events, llm_param, model, tools
from klaude_code.session.store import JsonlSessionStore, ProjectPaths, build_meta_snapshot

_DEFAULT_STORES: dict[str, JsonlSessionStore] = {}


def _project_key_from_cwd() -> str:
    return str(Path.cwd()).strip("/").replace("/", "-")


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return cast(dict[str, Any], raw)


def get_default_store() -> JsonlSessionStore:
    project_key = _project_key_from_cwd()
    store = _DEFAULT_STORES.get(project_key)
    if store is None:
        store = JsonlSessionStore(project_key=project_key)
        _DEFAULT_STORES[project_key] = store
    return store


async def close_default_store() -> None:
    stores = list(_DEFAULT_STORES.values())
    _DEFAULT_STORES.clear()
    for store in stores:
        await store.aclose()


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    work_dir: Path
    conversation_history: list[model.ConversationItem] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    sub_agent_state: model.SubAgentState | None = None
    file_tracker: dict[str, model.FileStatus] = Field(default_factory=dict)
    todos: list[model.TodoItem] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    model_name: str | None = None

    model_config_name: str | None = None
    model_thinking: llm_param.Thinking | None = None
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())
    need_todo_empty_cooldown_counter: int = Field(exclude=True, default=0)
    need_todo_not_used_cooldown_counter: int = Field(exclude=True, default=0)

    _messages_count_cache: int | None = PrivateAttr(default=None)
    _store: JsonlSessionStore = PrivateAttr(default_factory=get_default_store)

    @property
    def messages_count(self) -> int:
        """Count of user, assistant messages, and tool calls in conversation history."""
        if self._messages_count_cache is None:
            self._messages_count_cache = sum(
                1
                for it in self.conversation_history
                if isinstance(it, (model.UserMessageItem, model.AssistantMessageItem, model.ToolCallItem))
            )
        return self._messages_count_cache

    def _invalidate_messages_count_cache(self) -> None:
        self._messages_count_cache = None

    @staticmethod
    def _project_key() -> str:
        return _project_key_from_cwd()

    @classmethod
    def paths(cls) -> ProjectPaths:
        return get_default_store().paths

    @classmethod
    def exists(cls, id: str) -> bool:
        """Return True if a persisted session exists for the current project."""

        paths = cls.paths()
        return paths.meta_file(id).exists() or paths.events_file(id).exists()

    @classmethod
    def create(cls, id: str | None = None, *, work_dir: Path | None = None) -> Session:
        session = Session(id=id or uuid.uuid4().hex, work_dir=work_dir or Path.cwd())
        session._store = get_default_store()
        return session

    @classmethod
    def load_meta(cls, id: str) -> Session:
        store = get_default_store()
        raw = store.load_meta(id)
        if raw is None:
            session = Session(id=id, work_dir=Path.cwd())
            session._store = store
            return session

        work_dir_str = raw.get("work_dir")
        if not isinstance(work_dir_str, str) or not work_dir_str:
            work_dir_str = str(Path.cwd())

        sub_agent_state_raw = raw.get("sub_agent_state")
        sub_agent_state = (
            model.SubAgentState.model_validate(sub_agent_state_raw) if isinstance(sub_agent_state_raw, dict) else None
        )

        file_tracker_raw = raw.get("file_tracker")
        file_tracker: dict[str, model.FileStatus] = {}
        if isinstance(file_tracker_raw, dict):
            for k, v in cast(dict[object, object], file_tracker_raw).items():
                if isinstance(k, str) and isinstance(v, dict):
                    try:
                        file_tracker[k] = model.FileStatus.model_validate(v)
                    except ValidationError:
                        continue

        todos_raw = raw.get("todos")
        todos: list[model.TodoItem] = []
        if isinstance(todos_raw, list):
            for todo_raw in cast(list[object], todos_raw):
                if not isinstance(todo_raw, dict):
                    continue
                try:
                    todos.append(model.TodoItem.model_validate(todo_raw))
                except ValidationError:
                    continue

        created_at = float(raw.get("created_at", time.time()))
        updated_at = float(raw.get("updated_at", created_at))
        model_name = raw.get("model_name") if isinstance(raw.get("model_name"), str) else None
        model_config_name = raw.get("model_config_name") if isinstance(raw.get("model_config_name"), str) else None

        model_thinking_raw = raw.get("model_thinking")
        model_thinking = (
            llm_param.Thinking.model_validate(model_thinking_raw) if isinstance(model_thinking_raw, dict) else None
        )

        session = Session(
            id=id,
            work_dir=Path(work_dir_str),
            sub_agent_state=sub_agent_state,
            file_tracker=file_tracker,
            todos=todos,
            created_at=created_at,
            updated_at=updated_at,
            model_name=model_name,
            model_config_name=model_config_name,
            model_thinking=model_thinking,
        )
        session._store = store
        return session

    @classmethod
    def load(cls, id: str) -> Session:
        store = get_default_store()
        session = cls.load_meta(id)
        session._store = store
        session.conversation_history = store.load_history(id)
        return session

    def append_history(self, items: Sequence[model.ConversationItem]) -> None:
        if not items:
            return

        self.conversation_history.extend(items)
        self._invalidate_messages_count_cache()

        if self.created_at <= 0:
            self.created_at = time.time()
        self.updated_at = time.time()

        meta = build_meta_snapshot(
            session_id=self.id,
            work_dir=self.work_dir,
            sub_agent_state=self.sub_agent_state,
            file_tracker=self.file_tracker,
            todos=list(self.todos),
            created_at=self.created_at,
            updated_at=self.updated_at,
            messages_count=self.messages_count,
            model_name=self.model_name,
            model_config_name=self.model_config_name,
            model_thinking=self.model_thinking,
        )
        self._store.append_and_flush(session_id=self.id, items=items, meta=meta)

    def fork(self, *, new_id: str | None = None, until_index: int | None = None) -> Session:
        """Create a new session as a fork of the current session.

        The forked session copies metadata and conversation history, but does not
        modify the current session.

        Args:
            new_id: Optional ID for the forked session.
            until_index: If provided, only copy conversation history up to (but not including) this index.
                         If None, copy all history.
        """

        forked = Session.create(id=new_id, work_dir=self.work_dir)

        forked.sub_agent_state = None
        forked.model_name = self.model_name
        forked.model_config_name = self.model_config_name
        forked.model_thinking = self.model_thinking.model_copy(deep=True) if self.model_thinking is not None else None
        forked.file_tracker = {k: v.model_copy(deep=True) for k, v in self.file_tracker.items()}
        forked.todos = [todo.model_copy(deep=True) for todo in self.todos]

        history_to_copy = (
            self.conversation_history[:until_index] if until_index is not None else self.conversation_history
        )
        items = [it.model_copy(deep=True) for it in history_to_copy]
        if items:
            forked.append_history(items)

        return forked

    async def wait_for_flush(self) -> None:
        await self._store.wait_for_flush(self.id)

    @classmethod
    def most_recent_session_id(cls) -> str | None:
        store = get_default_store()
        latest_id: str | None = None
        latest_ts: float = -1.0
        for meta_path in store.iter_meta_files():
            data = _read_json_dict(meta_path)
            if data is None:
                continue
            if data.get("sub_agent_state") is not None:
                continue
            sid = str(data.get("id", meta_path.parent.name))
            try:
                ts = float(data.get("updated_at", 0.0))
            except (TypeError, ValueError):
                ts = meta_path.stat().st_mtime
            if ts > latest_ts:
                latest_ts = ts
                latest_id = sid
        return latest_id

    def need_turn_start(self, prev_item: model.ConversationItem | None, item: model.ConversationItem) -> bool:
        if not isinstance(
            item,
            model.ReasoningTextItem | model.AssistantMessageItem | model.ToolCallItem,
        ):
            return False
        if prev_item is None:
            return True
        return isinstance(prev_item, model.UserMessageItem | model.ToolResultItem | model.DeveloperMessageItem)

    def get_history_item(self) -> Iterable[events.HistoryItemEvent]:
        seen_sub_agent_sessions: set[str] = set()
        prev_item: model.ConversationItem | None = None
        last_assistant_content: str = ""
        report_back_result: str | None = None
        yield events.TaskStartEvent(session_id=self.id, sub_agent_state=self.sub_agent_state)
        for it in self.conversation_history:
            if self.need_turn_start(prev_item, it):
                yield events.TurnStartEvent(session_id=self.id)
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
                    yield events.UserMessageEvent(content=um.content or "", session_id=self.id, images=um.images)
                case model.ReasoningTextItem() as ri:
                    yield events.ThinkingEvent(content=ri.content, session_id=self.id)
                case model.TaskMetadataItem() as mt:
                    yield events.TaskMetadataEvent(session_id=self.id, metadata=mt)
                case model.InterruptItem():
                    yield events.InterruptEvent(session_id=self.id)
                case model.DeveloperMessageItem() as dm:
                    yield events.DeveloperMessageEvent(session_id=self.id, item=dm)
                case model.StreamErrorItem() as se:
                    yield events.ErrorEvent(error_message=se.error, can_retry=False)
                case _:
                    continue
            prev_item = it

        has_structured_output = report_back_result is not None
        task_result = report_back_result if has_structured_output else last_assistant_content
        yield events.TaskFinishEvent(
            session_id=self.id, task_result=task_result, has_structured_output=has_structured_output
        )

    def _iter_sub_agent_history(
        self, tool_result: model.ToolResultItem, seen_sub_agent_sessions: set[str]
    ) -> Iterable[events.HistoryItemEvent]:
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
        except (OSError, json.JSONDecodeError, ValueError):
            return
        yield from sub_session.get_history_item()

    class SessionMetaBrief(BaseModel):
        id: str
        created_at: float
        updated_at: float
        work_dir: str
        path: str
        user_messages: list[str] = []
        messages_count: int = -1
        model_name: str | None = None

    @classmethod
    def list_sessions(cls) -> list[SessionMetaBrief]:
        store = get_default_store()

        def _get_user_messages(session_id: str) -> list[str]:
            events_path = store.paths.events_file(session_id)
            if not events_path.exists():
                return []
            messages: list[str] = []
            try:
                for line in events_path.read_text(encoding="utf-8").splitlines():
                    obj_raw = json.loads(line)
                    if not isinstance(obj_raw, dict):
                        continue
                    obj = cast(dict[str, Any], obj_raw)
                    if obj.get("type") != "UserMessageItem":
                        continue
                    data_raw = obj.get("data")
                    if not isinstance(data_raw, dict):
                        continue
                    data = cast(dict[str, Any], data_raw)
                    content = data.get("content")
                    if isinstance(content, str):
                        messages.append(content)
            except (OSError, json.JSONDecodeError):
                pass
            return messages

        items: list[Session.SessionMetaBrief] = []
        for meta_path in store.iter_meta_files():
            data = _read_json_dict(meta_path)
            if data is None:
                continue
            if data.get("sub_agent_state") is not None:
                continue

            sid = str(data.get("id", meta_path.parent.name))
            created = float(data.get("created_at", meta_path.stat().st_mtime))
            updated = float(data.get("updated_at", meta_path.stat().st_mtime))
            work_dir = str(data.get("work_dir", ""))
            user_messages = _get_user_messages(sid)
            messages_count = int(data.get("messages_count", -1))
            model_name = data.get("model_name") if isinstance(data.get("model_name"), str) else None

            items.append(
                Session.SessionMetaBrief(
                    id=sid,
                    created_at=created,
                    updated_at=updated,
                    work_dir=work_dir,
                    path=str(meta_path),
                    user_messages=user_messages,
                    messages_count=messages_count,
                    model_name=model_name,
                )
            )

        items.sort(key=lambda d: d.updated_at, reverse=True)
        return items

    @classmethod
    def clean_small_sessions(cls, min_messages: int = 5) -> int:
        sessions = cls.list_sessions()
        deleted_count = 0
        store = get_default_store()
        for session_meta in sessions:
            if session_meta.messages_count < 0:
                continue
            if session_meta.messages_count < min_messages:
                store.delete_session(session_meta.id)
                deleted_count += 1
        return deleted_count

    @classmethod
    def clean_all_sessions(cls) -> int:
        sessions = cls.list_sessions()
        deleted_count = 0
        store = get_default_store()
        for session_meta in sessions:
            store.delete_session(session_meta.id)
            deleted_count += 1
        return deleted_count

    @classmethod
    def exports_dir(cls) -> Path:
        return get_default_store().paths.exports_dir
