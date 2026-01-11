from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field, PrivateAttr, ValidationError

from klaude_code.const import ProjectPaths, project_key_from_cwd
from klaude_code.protocol import events, llm_param, message, model, tools
from klaude_code.session.store import JsonlSessionStore, build_meta_snapshot

_DEFAULT_STORES: dict[str, JsonlSessionStore] = {}


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return cast(dict[str, Any], raw)


def get_default_store() -> JsonlSessionStore:
    project_key = project_key_from_cwd()
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
    conversation_history: list[message.HistoryEvent] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
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
    _user_messages_cache: list[str] | None = PrivateAttr(default=None)
    _store: JsonlSessionStore = PrivateAttr(default_factory=get_default_store)

    @property
    def messages_count(self) -> int:
        """Count of user, assistant messages, and tool results in conversation history."""
        if self._messages_count_cache is None:
            self._messages_count_cache = sum(
                1
                for it in self.conversation_history
                if isinstance(it, (message.UserMessage, message.AssistantMessage, message.ToolResultMessage))
            )
        return self._messages_count_cache

    def _invalidate_messages_count_cache(self) -> None:
        self._messages_count_cache = None

    @property
    def user_messages(self) -> list[str]:
        """All user message contents in this session.

        This is used for session selection UI and search, and is also persisted
        in meta.json to avoid scanning events.jsonl for every session.
        """

        if self._user_messages_cache is None:
            self._user_messages_cache = [
                message.join_text_parts(it.parts)
                for it in self.conversation_history
                if isinstance(it, message.UserMessage) and message.join_text_parts(it.parts)
            ]
        return self._user_messages_cache

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

    def append_history(self, items: Sequence[message.HistoryEvent]) -> None:
        if not items:
            return

        self.conversation_history.extend(items)
        self._invalidate_messages_count_cache()

        new_user_messages = [
            message.join_text_parts(it.parts)
            for it in items
            if isinstance(it, message.UserMessage) and message.join_text_parts(it.parts)
        ]
        if new_user_messages:
            if self._user_messages_cache is None:
                # Build from full history once to ensure correctness when resuming older sessions.
                self._user_messages_cache = [
                    message.join_text_parts(it.parts)
                    for it in self.conversation_history
                    if isinstance(it, message.UserMessage) and message.join_text_parts(it.parts)
                ]
            else:
                self._user_messages_cache.extend(new_user_messages)

        if self.created_at <= 0:
            self.created_at = time.time()
        self.updated_at = time.time()

        meta = build_meta_snapshot(
            session_id=self.id,
            work_dir=self.work_dir,
            sub_agent_state=self.sub_agent_state,
            file_tracker=self.file_tracker,
            todos=list(self.todos),
            user_messages=self.user_messages,
            created_at=self.created_at,
            updated_at=self.updated_at,
            messages_count=self.messages_count,
            model_name=self.model_name,
            model_config_name=self.model_config_name,
            model_thinking=self.model_thinking,
        )
        self._store.append_and_flush(session_id=self.id, items=items, meta=meta)

    def get_llm_history(self) -> list[message.HistoryEvent]:
        """Return the LLM-facing history view with compaction summary injected."""
        history = self.conversation_history
        last_compaction: message.CompactionEntry | None = None
        for item in reversed(history):
            if isinstance(item, message.CompactionEntry):
                last_compaction = item
                break
        if last_compaction is None:
            return [it for it in history if not isinstance(it, message.CompactionEntry)]

        summary_message = message.UserMessage(parts=[message.TextPart(text=last_compaction.summary)])
        kept = [it for it in history[last_compaction.first_kept_index :] if not isinstance(it, message.CompactionEntry)]

        # Guard against old/bad persisted compaction boundaries that start with tool results.
        # Tool results must not appear without their corresponding assistant tool call.
        if kept and isinstance(kept[0], message.ToolResultMessage):
            first_non_tool = 0
            while first_non_tool < len(kept) and isinstance(kept[first_non_tool], message.ToolResultMessage):
                first_non_tool += 1
            kept = kept[first_non_tool:]

        return [summary_message, *kept]

    def fork(self, *, new_id: str | None = None, until_index: int | None = None) -> Session:
        """Create a new session as a fork of the current session.

        The forked session copies metadata and conversation history, but does not
        modify the current session.

        Args:
            new_id: Optional ID for the forked session.
            until_index: If provided, only copy conversation history up to (but not including) this index.
                         If -1, copy all history.
        """

        forked = Session.create(id=new_id, work_dir=self.work_dir)

        forked.sub_agent_state = None
        forked.model_name = self.model_name
        forked.model_config_name = self.model_config_name
        forked.model_thinking = self.model_thinking.model_copy(deep=True) if self.model_thinking is not None else None
        forked.file_tracker = {k: v.model_copy(deep=True) for k, v in self.file_tracker.items()}
        forked.todos = [todo.model_copy(deep=True) for todo in self.todos]

        history_to_copy = (
            self.conversation_history[:until_index]
            if (until_index is not None and until_index >= 0)
            else self.conversation_history
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

    def need_turn_start(self, prev_item: message.HistoryEvent | None, item: message.HistoryEvent) -> bool:
        if not isinstance(item, message.AssistantMessage):
            return False
        if prev_item is None:
            return True
        return isinstance(prev_item, (message.UserMessage, message.ToolResultMessage, message.DeveloperMessage))

    def get_history_item(self) -> Iterable[events.ReplayEventUnion]:
        seen_sub_agent_sessions: set[str] = set()
        prev_item: message.HistoryEvent | None = None
        last_assistant_content: str = ""
        report_back_result: str | None = None
        pending_tool_calls: dict[str, events.ToolCallEvent] = {}
        history = self.conversation_history
        history_len = len(history)
        yield events.TaskStartEvent(session_id=self.id, sub_agent_state=self.sub_agent_state)
        for idx, it in enumerate(history):
            # Flush pending tool calls if current item won't consume them
            if pending_tool_calls and not isinstance(it, message.ToolResultMessage):
                yield from pending_tool_calls.values()
                pending_tool_calls.clear()
            if self.need_turn_start(prev_item, it):
                yield events.TurnStartEvent(session_id=self.id)
            match it:
                case message.AssistantMessage() as am:
                    all_images = [part for part in am.parts if isinstance(part, message.ImageFilePart)]
                    full_content = message.join_text_parts(am.parts)
                    last_assistant_content = message.format_saved_images(all_images, full_content)

                    # Reconstruct streaming boundaries from saved parts.
                    # This allows replay to reuse the same TUI state machine as live events.
                    thinking_open = False
                    thinking_had_content = False
                    assistant_open = False

                    for part in am.parts:
                        if isinstance(part, message.ThinkingTextPart):
                            if assistant_open:
                                assistant_open = False
                                yield events.AssistantTextEndEvent(response_id=am.response_id, session_id=self.id)
                            if not thinking_open:
                                thinking_open = True
                                yield events.ThinkingStartEvent(response_id=am.response_id, session_id=self.id)
                            if part.text:
                                if thinking_had_content:
                                    yield events.ThinkingDeltaEvent(
                                        content="  \n  \n",
                                        response_id=am.response_id,
                                        session_id=self.id,
                                    )
                                yield events.ThinkingDeltaEvent(
                                    content=part.text,
                                    response_id=am.response_id,
                                    session_id=self.id,
                                )
                                thinking_had_content = True
                            continue

                        if thinking_open:
                            thinking_open = False
                            thinking_had_content = False
                            yield events.ThinkingEndEvent(response_id=am.response_id, session_id=self.id)

                        if isinstance(part, message.TextPart):
                            if not assistant_open:
                                assistant_open = True
                                yield events.AssistantTextStartEvent(response_id=am.response_id, session_id=self.id)
                            if part.text:
                                yield events.AssistantTextDeltaEvent(
                                    content=part.text,
                                    response_id=am.response_id,
                                    session_id=self.id,
                                )
                        elif isinstance(part, message.ImageFilePart):
                            yield events.AssistantImageDeltaEvent(
                                file_path=part.file_path,
                                response_id=am.response_id,
                                session_id=self.id,
                            )

                    if thinking_open:
                        yield events.ThinkingEndEvent(response_id=am.response_id, session_id=self.id)
                    if assistant_open:
                        yield events.AssistantTextEndEvent(response_id=am.response_id, session_id=self.id)

                    for part in am.parts:
                        if not isinstance(part, message.ToolCallPart):
                            continue
                        if part.tool_name == tools.REPORT_BACK:
                            report_back_result = part.arguments_json
                        pending_tool_calls[part.call_id] = events.ToolCallEvent(
                            tool_call_id=part.call_id,
                            tool_name=part.tool_name,
                            arguments=part.arguments_json,
                            response_id=am.response_id,
                            session_id=self.id,
                        )
                    if am.stop_reason == "aborted":
                        yield events.InterruptEvent(session_id=self.id)
                case message.ToolResultMessage() as tr:
                    if tr.call_id in pending_tool_calls:
                        yield pending_tool_calls.pop(tr.call_id)
                    status = "success" if tr.status == "success" else "error"
                    # Check if this is the last tool result in the current turn
                    next_item = history[idx + 1] if idx + 1 < history_len else None
                    is_last_in_turn = not isinstance(next_item, message.ToolResultMessage)
                    yield events.ToolResultEvent(
                        tool_call_id=tr.call_id,
                        tool_name=str(tr.tool_name),
                        result=tr.output_text,
                        ui_extra=tr.ui_extra,
                        session_id=self.id,
                        status=status,
                        task_metadata=tr.task_metadata,
                        is_last_in_turn=is_last_in_turn,
                    )
                    yield from self._iter_sub_agent_history(tr, seen_sub_agent_sessions)
                case message.UserMessage() as um:
                    images = [
                        part for part in um.parts if isinstance(part, (message.ImageURLPart, message.ImageFilePart))
                    ]
                    yield events.UserMessageEvent(
                        content=message.join_text_parts(um.parts),
                        session_id=self.id,
                        images=images or None,
                    )
                case model.TaskMetadataItem() as mt:
                    if self.sub_agent_state is None:
                        yield events.TaskMetadataEvent(session_id=self.id, metadata=mt)
                case message.DeveloperMessage() as dm:
                    yield events.DeveloperMessageEvent(session_id=self.id, item=dm)
                case message.StreamErrorItem() as se:
                    yield events.ErrorEvent(error_message=se.error, can_retry=False, session_id=self.id)
                case message.CompactionEntry() as ce:
                    yield events.CompactionStartEvent(session_id=self.id, reason="threshold")
                    yield events.CompactionEndEvent(
                        session_id=self.id,
                        reason="threshold",
                        aborted=False,
                        will_retry=False,
                        tokens_before=ce.tokens_before,
                        kept_from_index=ce.first_kept_index,
                        summary=ce.summary,
                        kept_items_brief=ce.kept_items_brief,
                    )
                case message.SystemMessage():
                    pass
            prev_item = it

        # Flush any remaining pending tool calls (e.g., from aborted or incomplete sessions)
        if pending_tool_calls:
            yield from pending_tool_calls.values()
            pending_tool_calls.clear()

        has_structured_output = report_back_result is not None
        task_result = report_back_result if has_structured_output else last_assistant_content

        if self.sub_agent_state is not None:
            trimmed = (task_result or "").rstrip()
            lines = trimmed.splitlines()
            if not (lines and lines[-1].startswith("agentId:")):
                footer = f"agentId: {self.id} (for resuming to continue this agent's work if needed)"
                task_result = f"{trimmed}\n\n{footer}" if trimmed.strip() else footer

        yield events.TaskFinishEvent(
            session_id=self.id, task_result=task_result or "", has_structured_output=has_structured_output
        )

    def _iter_sub_agent_history(
        self, tool_result: message.ToolResultMessage, seen_sub_agent_sessions: set[str]
    ) -> Iterable[events.ReplayEventUnion]:
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
                    if obj.get("type") != "UserMessage":
                        continue
                    data_raw = obj.get("data")
                    if not isinstance(data_raw, dict):
                        continue
                    data = cast(dict[str, Any], data_raw)
                    try:
                        user_msg = message.UserMessage.model_validate(data)
                    except ValidationError:
                        continue
                    content = message.join_text_parts(user_msg.parts)
                    if content:
                        messages.append(content)
            except (OSError, json.JSONDecodeError):
                pass
            return messages

        def _maybe_backfill_user_messages(*, meta_path: Path, meta: dict[str, Any], user_messages: list[str]) -> None:
            if isinstance(meta.get("user_messages"), list):
                return
            meta["user_messages"] = user_messages
            try:
                tmp_path = meta_path.with_suffix(".json.tmp")
                tmp_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp_path.replace(meta_path)
            except OSError:
                return

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

            user_messages_raw = data.get("user_messages")
            if isinstance(user_messages_raw, list) and all(
                isinstance(m, str) for m in cast(list[object], user_messages_raw)
            ):
                user_messages = cast(list[str], user_messages_raw)
            else:
                user_messages = _get_user_messages(sid)
                _maybe_backfill_user_messages(meta_path=meta_path, meta=data, user_messages=user_messages)
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
    def resolve_sub_agent_session_id(cls, resume: str) -> str:
        """Resolve a sub-agent session id from an id prefix.

        Args:
            resume: Full session id or a unique prefix.

        Returns:
            The resolved full session id.

        Raises:
            ValueError: If resume is empty, not found, or ambiguous.
        """

        prefix = (resume or "").strip().lower()
        if not prefix:
            raise ValueError("resume cannot be empty")

        store = get_default_store()
        matches: set[str] = set()

        for meta_path in store.iter_meta_files():
            data = _read_json_dict(meta_path)
            if data is None:
                continue
            # Only allow resuming sub-agent sessions.
            if data.get("sub_agent_state") is None:
                continue
            sid = str(data.get("id", meta_path.parent.name)).strip()
            if sid.lower().startswith(prefix):
                matches.add(sid)

        if not matches:
            raise ValueError(f"resume id not found for this project: '{resume}'")

        resolved = sorted(matches)
        if len(resolved) > 1:
            sample = ", ".join(resolved[:8])
            suffix = "" if len(resolved) <= 8 else f" (+{len(resolved) - 8} more)"
            raise ValueError(f"resume id is ambiguous: '{resume}' matches {sample}{suffix}")

        return resolved[0]

    @classmethod
    def find_sessions_by_prefix(cls, prefix: str) -> list[str]:
        """Find main session IDs matching a prefix.

        Args:
            prefix: Session ID prefix to match.

        Returns:
            List of matching session IDs, sorted alphabetically.
        """
        prefix = (prefix or "").strip().lower()
        if not prefix:
            return []

        store = get_default_store()
        matches: set[str] = set()

        for meta_path in store.iter_meta_files():
            data = _read_json_dict(meta_path)
            if data is None:
                continue
            # Exclude sub-agent sessions.
            if data.get("sub_agent_state") is not None:
                continue
            sid = str(data.get("id", meta_path.parent.name)).strip()
            if sid.lower().startswith(prefix):
                matches.add(sid)

        return sorted(matches)

    @classmethod
    def shortest_unique_prefix(cls, session_id: str, min_length: int = 4) -> str:
        """Find the shortest unique prefix for a session ID.

        Args:
            session_id: The session ID to find prefix for.
            min_length: Minimum prefix length (default 4).

        Returns:
            The shortest prefix that uniquely identifies this session.
        """
        store = get_default_store()
        other_ids: list[str] = []

        for meta_path in store.iter_meta_files():
            data = _read_json_dict(meta_path)
            if data is None:
                continue
            if data.get("sub_agent_state") is not None:
                continue
            sid = str(data.get("id", meta_path.parent.name)).strip()
            if sid != session_id:
                other_ids.append(sid.lower())

        session_lower = session_id.lower()
        for length in range(min_length, len(session_id) + 1):
            prefix = session_lower[:length]
            if not any(other.startswith(prefix) for other in other_ids):
                return session_id[:length]

        return session_id

    @classmethod
    def exports_dir(cls) -> Path:
        return get_default_store().paths.exports_dir
