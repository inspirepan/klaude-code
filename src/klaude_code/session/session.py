from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field, PrivateAttr, ValidationError

from klaude_code.const import ProjectPaths
from klaude_code.prompts.messages import CHECKPOINT_TEMPLATE, REWIND_REMINDER_TEMPLATE, TOOL_INTERRUPTED_MESSAGE
from klaude_code.protocol import events, llm_param, message
from klaude_code.protocol.models import (
    FileChangeSummary,
    FileStatus,
    SessionIdUIExtra,
    SessionOwner,
    SessionRuntimeState,
    SubAgentState,
    TaskMetadataItem,
    TodoItem,
)
from klaude_code.session.history import (
    extract_checkpoint_id,
    extract_xml_tag,
    find_checkpoint_index_in_history,
    rebuild_loaded_history,
)
from klaude_code.session.meta import parse_session_meta, parse_session_state, read_json_dict
from klaude_code.session.store import JsonlSessionStore, build_meta_snapshot
from klaude_code.session.store_registry import get_store_for_path


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    work_dir: Path
    title: str | None = None
    conversation_history: list[message.HistoryEvent] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    sub_agent_state: SubAgentState | None = None
    file_tracker: dict[str, FileStatus] = Field(default_factory=dict)
    file_change_summary: FileChangeSummary = Field(default_factory=FileChangeSummary)
    todos: list[TodoItem] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    model_name: str | None = None
    session_state: SessionRuntimeState | None = None
    runtime_owner: SessionOwner | None = None
    runtime_owner_heartbeat_at: float | None = None
    archived: bool = False

    next_checkpoint_id: int = 0

    model_config_name: str | None = None
    model_thinking: llm_param.Thinking | None = None
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())
    need_todo_empty_cooldown_counter: int = Field(exclude=True, default=0)
    need_todo_not_used_cooldown_counter: int = Field(exclude=True, default=0)

    _messages_count_cache: int | None = PrivateAttr(default=None)
    _user_messages_cache: list[str] | None = PrivateAttr(default=None)
    _store: JsonlSessionStore = PrivateAttr(default=None)  # type: ignore[assignment]  # set in model_post_init

    def model_post_init(self, __context: Any) -> None:
        self._store = get_store_for_path(self.work_dir)

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
    def paths(cls, work_dir: Path) -> ProjectPaths:
        return get_store_for_path(work_dir).paths

    @classmethod
    def exists(cls, id: str, work_dir: Path) -> bool:
        """Return True if a persisted session exists for the given project."""

        paths = cls.paths(work_dir)
        return paths.meta_file(id).exists() or paths.events_file(id).exists()

    @classmethod
    def has_user_messages(cls, id: str, work_dir: Path) -> bool:
        """Return True when the session contains at least one non-empty user message."""

        raw = read_json_dict(cls.paths(work_dir).meta_file(id))
        if raw is not None:
            user_messages_raw = raw.get("user_messages")
            if isinstance(user_messages_raw, list):
                return any(isinstance(msg, str) and bool(msg.strip()) for msg in cast(list[object], user_messages_raw))

        try:
            return bool(cls.load(id, work_dir=work_dir).user_messages)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError):
            return False

    @classmethod
    def create(cls, id: str | None = None, *, work_dir: Path) -> Session:
        return Session(id=id or uuid.uuid4().hex, work_dir=work_dir)

    @classmethod
    def load_meta(cls, id: str, work_dir: Path) -> Session:
        store = get_store_for_path(work_dir)
        raw = store.load_meta(id)
        if raw is None:
            return Session(id=id, work_dir=work_dir)

        meta = parse_session_meta(raw, work_dir=work_dir)

        return Session(
            id=id,
            work_dir=meta.work_dir,
            sub_agent_state=meta.sub_agent_state,
            file_tracker=meta.file_tracker,
            file_change_summary=meta.file_change_summary,
            todos=meta.todos,
            created_at=meta.created_at,
            updated_at=meta.updated_at,
            title=meta.title,
            model_name=meta.model_name,
            session_state=meta.session_state,
            runtime_owner=meta.runtime_owner,
            runtime_owner_heartbeat_at=meta.runtime_owner_heartbeat_at,
            archived=meta.archived,
            model_config_name=meta.model_config_name,
            model_thinking=meta.model_thinking,
            next_checkpoint_id=meta.next_checkpoint_id,
        )

    @classmethod
    def load(cls, id: str, work_dir: Path) -> Session:
        session = cls.load_meta(id, work_dir)
        session.conversation_history = rebuild_loaded_history(session._store.iter_history(id))
        return session

    @classmethod
    def persist_runtime_state(cls, session_id: str, session_state: SessionRuntimeState, work_dir: Path) -> None:
        store = get_store_for_path(work_dir)
        # Runtime state transitions should not affect session recency ordering.
        # Only content writes (append_history) update `updated_at`.
        store.update_meta(session_id, {"session_state": session_state.value})

    @classmethod
    def persist_runtime_owner(cls, session_id: str, runtime_owner: SessionOwner | None, work_dir: Path) -> None:
        store = get_store_for_path(work_dir)
        store.update_meta(
            session_id,
            {
                "runtime_owner": runtime_owner.model_dump(mode="json") if runtime_owner is not None else None,
                "runtime_owner_heartbeat_at": time.time() if runtime_owner is not None else None,
            },
        )

    @classmethod
    def persist_runtime_owner_heartbeat(cls, session_id: str, timestamp: float, work_dir: Path) -> None:
        store = get_store_for_path(work_dir)
        store.update_meta(session_id, {"runtime_owner_heartbeat_at": timestamp})

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
            title=self.title,
            sub_agent_state=self.sub_agent_state,
            file_tracker=self.file_tracker,
            file_change_summary=self.file_change_summary,
            todos=list(self.todos),
            user_messages=self.user_messages,
            created_at=self.created_at,
            updated_at=self.updated_at,
            messages_count=self.messages_count,
            model_name=self.model_name,
            session_state=self.session_state,
            runtime_owner=self.runtime_owner,
            runtime_owner_heartbeat_at=self.runtime_owner_heartbeat_at,
            archived=self.archived,
            model_config_name=self.model_config_name,
            model_thinking=self.model_thinking,
            next_checkpoint_id=self.next_checkpoint_id,
        )
        self._store.append_and_flush(session_id=self.id, items=items, meta=meta)

    def update_title(self, title: str | None) -> bool:
        normalized = title.strip() if isinstance(title, str) else None
        if normalized == "":
            normalized = None
        if self.title == normalized:
            return False
        self.title = normalized
        self._store.update_meta(self.id, {"title": normalized})
        return True

    def ensure_meta_exists(self) -> None:
        meta = build_meta_snapshot(
            session_id=self.id,
            work_dir=self.work_dir,
            title=self.title,
            sub_agent_state=self.sub_agent_state,
            file_tracker=self.file_tracker,
            file_change_summary=self.file_change_summary,
            todos=list(self.todos),
            user_messages=self.user_messages,
            created_at=self.created_at,
            updated_at=self.updated_at,
            messages_count=self.messages_count,
            model_name=self.model_name,
            session_state=self.session_state,
            runtime_owner=self.runtime_owner,
            runtime_owner_heartbeat_at=self.runtime_owner_heartbeat_at,
            archived=self.archived,
            model_config_name=self.model_config_name,
            model_thinking=self.model_thinking,
            next_checkpoint_id=self.next_checkpoint_id,
        )
        self._store.create_meta_if_missing(self.id, meta)

    @property
    def n_checkpoints(self) -> int:
        return self.next_checkpoint_id

    def create_checkpoint(self) -> int:
        checkpoint_id = self.next_checkpoint_id
        self.next_checkpoint_id += 1
        checkpoint_msg = message.DeveloperMessage(
            parts=[message.TextPart(text=CHECKPOINT_TEMPLATE.format(checkpoint_id=checkpoint_id))]
        )
        self.append_history([checkpoint_msg])
        return checkpoint_id

    def find_checkpoint_index(self, checkpoint_id: int) -> int | None:
        return find_checkpoint_index_in_history(self.conversation_history, checkpoint_id)

    def get_user_message_before_checkpoint(self, checkpoint_id: int) -> str | None:
        checkpoint_idx = self.find_checkpoint_index(checkpoint_id)
        if checkpoint_idx is None:
            return None

        for i in range(checkpoint_idx - 1, -1, -1):
            item = self.conversation_history[i]
            if isinstance(item, message.UserMessage):
                return message.join_text_parts(item.parts)
        return None

    def get_checkpoint_user_messages(self) -> dict[int, str]:
        checkpoints: dict[int, str] = {}
        last_user_message = ""
        for item in self.conversation_history:
            if isinstance(item, message.UserMessage):
                last_user_message = message.join_text_parts(item.parts)
                continue
            if not isinstance(item, message.DeveloperMessage):
                continue
            text = message.join_text_parts(item.parts)
            checkpoint_id = extract_checkpoint_id(text)
            if checkpoint_id is None:
                continue
            checkpoints[checkpoint_id] = last_user_message
        return checkpoints

    def revert_to_checkpoint(self, checkpoint_id: int, note: str, rationale: str) -> message.RewindEntry:
        target_idx = self.find_checkpoint_index(checkpoint_id)
        if target_idx is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        user_message = self.get_user_message_before_checkpoint(checkpoint_id) or ""
        reverted_from = len(self.conversation_history)
        entry = message.RewindEntry(
            checkpoint_id=checkpoint_id,
            note=note,
            rationale=rationale,
            reverted_from_index=reverted_from,
            original_user_message=user_message,
        )

        self.conversation_history = self.conversation_history[: target_idx + 1]
        self.next_checkpoint_id = checkpoint_id + 1
        self._invalidate_messages_count_cache()
        self._user_messages_cache = None
        return entry

    @staticmethod
    def _strip_dangling_tool_calls(items: list[message.HistoryEvent]) -> list[message.HistoryEvent]:
        """Patch dangling tool_call parts that have no matching ToolResultMessage.

        For each dangling tool_call, a synthetic aborted ToolResultMessage is
        appended right after the AssistantMessage so the LLM knows the call was
        interrupted.  All major LLM APIs require every tool_use to have a paired
        tool_result.
        """
        answered_call_ids: set[str] = {it.call_id for it in items if isinstance(it, message.ToolResultMessage)}

        result: list[message.HistoryEvent] = []
        for item in items:
            if not isinstance(item, message.AssistantMessage):
                result.append(item)
                continue

            result.append(item)

            for part in item.parts:
                if isinstance(part, message.ToolCallPart) and part.call_id not in answered_call_ids:
                    result.append(
                        message.ToolResultMessage(
                            call_id=part.call_id,
                            tool_name=part.tool_name,
                            output_text=TOOL_INTERRUPTED_MESSAGE,
                            status="error",
                        )
                    )

        return result

    def get_llm_history(self, *, until_index: int | None = None) -> list[message.HistoryEvent]:
        """Return the LLM-facing history view with compaction summary injected.

        When ``until_index`` is provided, only conversation items before that
        index are considered. Passing a cut index preserves cache prefix
        matching: the returned list shares its prefix with the un-cut view up
        to the same boundary the parent request saw.
        """
        history = self.conversation_history if until_index is None else self.conversation_history[:until_index]

        def _convert(item: message.HistoryEvent) -> message.HistoryEvent:
            if isinstance(item, message.RewindEntry):
                return message.DeveloperMessage(
                    parts=[
                        message.TextPart(text=REWIND_REMINDER_TEMPLATE.format(rationale=item.rationale, note=item.note))
                    ]
                )
            return item

        last_compaction: message.CompactionEntry | None = None
        last_compaction_idx: int = -1
        for idx in range(len(history) - 1, -1, -1):
            item = history[idx]
            if isinstance(item, message.CompactionEntry):
                last_compaction = item
                last_compaction_idx = idx
                break
        if last_compaction is None:
            result = [_convert(it) for it in history if not isinstance(it, message.CompactionEntry)]
            return self._strip_dangling_tool_calls(result)

        summary_message = message.UserMessage(parts=[message.TextPart(text=last_compaction.summary)])
        # Respect the slice: if first_kept_index points past ``history`` (e.g.
        # caller cut right after the CompactionEntry), fall back to items just
        # after the compaction boundary within the slice.
        kept_start = last_compaction.first_kept_index
        if kept_start > len(history):
            kept_start = last_compaction_idx + 1
        kept = [it for it in history[kept_start:] if not isinstance(it, message.CompactionEntry)]

        # Guard against old/bad persisted compaction boundaries that start with tool results.
        # Tool results must not appear without their corresponding assistant tool call.
        if kept and isinstance(kept[0], message.ToolResultMessage):
            first_non_tool = 0
            while first_non_tool < len(kept) and isinstance(kept[first_non_tool], message.ToolResultMessage):
                first_non_tool += 1
            kept = kept[first_non_tool:]

        result = [summary_message, *[_convert(it) for it in kept]]
        return self._strip_dangling_tool_calls(result)

    def fork(self, *, new_id: str | None = None, until_index: int | None = None) -> Session:
        """Create a new session as a fork of the current session.

        The forked session copies metadata and conversation history, but does not
        modify the current session.

        Args:
            new_id: Optional ID for the forked session.
            until_index: If provided, only copy conversation history up to (but not including) this index.
                         If -1, copy all history.
        """

        forked = Session(id=new_id or uuid.uuid4().hex, work_dir=self.work_dir)

        forked.sub_agent_state = None
        forked.model_name = self.model_name
        forked.model_config_name = self.model_config_name
        forked.model_thinking = self.model_thinking.model_copy(deep=True) if self.model_thinking is not None else None
        forked.next_checkpoint_id = self.next_checkpoint_id
        forked.file_tracker = {k: v.model_copy(deep=True) for k, v in self.file_tracker.items()}
        forked.file_change_summary = self.file_change_summary.model_copy(deep=True)
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
    def most_recent_session_id(cls, work_dir: Path) -> str | None:
        store = get_store_for_path(work_dir)
        latest_id: str | None = None
        latest_ts: float = -1.0
        for meta_path in store.iter_meta_files():
            data = read_json_dict(meta_path)
            if data is None:
                continue
            if data.get("sub_agent_state") is not None:
                continue
            if data.get("archived") is True:
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
        return isinstance(
            prev_item,
            (
                message.UserMessage,
                message.ToolResultMessage,
                message.DeveloperMessage,
                message.CacheHitRateEntry,
                message.CompactionEntry,
                message.InterruptEntry,
                message.RewindEntry,
            ),
        )

    def _has_task_completed(self) -> bool:
        """Check whether this session's task has completed (normally or via interruption)."""
        return any(isinstance(it, TaskMetadataItem) for it in self.conversation_history)

    def get_history_item(self, *, emit_finish: bool = True) -> Iterable[events.ReplayEventUnion]:
        seen_sub_agent_sessions: set[str] = set()
        prev_item: message.HistoryEvent | None = None
        last_assistant_content: str = ""
        pending_tool_calls: dict[str, events.ToolCallEvent] = {}
        had_any_turn = False
        task_finish_pending = False
        prev_turn_interrupted = False
        history = self.conversation_history
        history_len = len(history)
        yield events.TaskStartEvent(
            session_id=self.id,
            sub_agent_state=self.sub_agent_state,
            timestamp=self.created_at if self.created_at > 0 else time.time(),
        )
        msg_ts: float = 0.0

        def _flush_task_finish(timestamp: float) -> Iterable[events.TaskFinishEvent]:
            nonlocal prev_turn_interrupted, last_assistant_content, task_finish_pending
            if not task_finish_pending:
                return
            if not prev_turn_interrupted:
                yield events.TaskFinishEvent(
                    session_id=self.id,
                    task_result=last_assistant_content or "",
                    timestamp=timestamp,
                )
            prev_turn_interrupted = False
            last_assistant_content = ""
            task_finish_pending = False

        for idx, it in enumerate(history):
            # Track the original message creation time
            if hasattr(it, "created_at"):
                msg_ts = it.created_at.timestamp()

            # Flush pending tool calls if current item won't consume them
            if pending_tool_calls and not isinstance(it, message.ToolResultMessage):
                yield from pending_tool_calls.values()
                pending_tool_calls.clear()

            # Emit task boundary before user message to produce inter-turn separators during replay
            if isinstance(it, message.UserMessage) and had_any_turn:
                yield from _flush_task_finish(msg_ts)
                yield events.TaskStartEvent(
                    session_id=self.id,
                    sub_agent_state=self.sub_agent_state,
                    timestamp=msg_ts,
                )

            if self.need_turn_start(prev_item, it):
                yield events.TurnStartEvent(session_id=self.id, timestamp=msg_ts)
            match it:
                case message.AssistantMessage() as am:
                    had_any_turn = True
                    task_finish_pending = True
                    last_assistant_content = message.join_text_parts(am.parts)

                    # Reconstruct streaming boundaries from saved parts.
                    # This allows replay to reuse the same TUI state machine as live events.
                    thinking_open = False
                    thinking_had_content = False
                    assistant_open = False

                    for part in am.parts:
                        if isinstance(part, message.ThinkingTextPart):
                            if assistant_open:
                                assistant_open = False
                                yield events.AssistantTextEndEvent(
                                    response_id=am.response_id, session_id=self.id, timestamp=msg_ts
                                )
                            if not thinking_open:
                                thinking_open = True
                                yield events.ThinkingStartEvent(
                                    response_id=am.response_id, session_id=self.id, timestamp=msg_ts
                                )
                            if part.text:
                                if thinking_had_content:
                                    yield events.ThinkingDeltaEvent(
                                        content="  \n  \n",
                                        response_id=am.response_id,
                                        session_id=self.id,
                                        timestamp=msg_ts,
                                    )
                                yield events.ThinkingDeltaEvent(
                                    content=part.text,
                                    response_id=am.response_id,
                                    session_id=self.id,
                                    timestamp=msg_ts,
                                )
                                thinking_had_content = True
                            continue

                        if thinking_open:
                            thinking_open = False
                            thinking_had_content = False
                            yield events.ThinkingEndEvent(
                                response_id=am.response_id, session_id=self.id, timestamp=msg_ts
                            )

                        if isinstance(part, message.TextPart):
                            if not assistant_open:
                                assistant_open = True
                                yield events.AssistantTextStartEvent(
                                    response_id=am.response_id, session_id=self.id, timestamp=msg_ts
                                )
                            if part.text:
                                yield events.AssistantTextDeltaEvent(
                                    content=part.text,
                                    response_id=am.response_id,
                                    session_id=self.id,
                                    timestamp=msg_ts,
                                )

                    if thinking_open:
                        yield events.ThinkingEndEvent(response_id=am.response_id, session_id=self.id, timestamp=msg_ts)
                    if assistant_open:
                        yield events.AssistantTextEndEvent(
                            response_id=am.response_id, session_id=self.id, timestamp=msg_ts
                        )

                    for part in am.parts:
                        if not isinstance(part, message.ToolCallPart):
                            continue
                        pending_tool_calls[part.call_id] = events.ToolCallEvent(
                            tool_call_id=part.call_id,
                            tool_name=part.tool_name,
                            arguments=part.arguments_json,
                            response_id=am.response_id,
                            session_id=self.id,
                            timestamp=msg_ts,
                        )
                    if am.stop_reason == "aborted":
                        prev_turn_interrupted = True
                        yield events.InterruptEvent(session_id=self.id, timestamp=msg_ts)
                    if am.usage is not None:
                        yield events.UsageEvent(
                            session_id=self.id,
                            usage=am.usage,
                            response_id=am.response_id,
                            timestamp=msg_ts,
                        )
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
                        timestamp=msg_ts,
                    )
                    yield from self._iter_sub_agent_history(tr, seen_sub_agent_sessions)
                case message.UserMessage() as um:
                    if um.source == "bash_mode":
                        text = message.join_text_parts(um.parts)
                        cmd = extract_xml_tag(text, "bash-input")
                        if cmd:
                            yield events.UserMessageEvent(
                                content=f"!{cmd}",
                                session_id=self.id,
                                timestamp=msg_ts,
                            )
                            yield events.BashCommandStartEvent(session_id=self.id, command=cmd, timestamp=msg_ts)
                        stdout = extract_xml_tag(text, "bash-stdout")
                        if stdout and stdout != "(no output)":
                            yield events.BashCommandOutputDeltaEvent(
                                session_id=self.id, content=stdout, timestamp=msg_ts
                            )
                        yield events.BashCommandEndEvent(
                            session_id=self.id,
                            exit_code=None,
                            cancelled="(command cancelled)" in (stdout or ""),
                            timestamp=msg_ts,
                        )
                    else:
                        images = [
                            part for part in um.parts if isinstance(part, (message.ImageURLPart, message.ImageFilePart))
                        ]
                        yield events.UserMessageEvent(
                            content=message.join_text_parts(um.parts),
                            session_id=self.id,
                            images=images or None,
                            timestamp=msg_ts,
                        )
                case TaskMetadataItem() as mt:
                    yield events.TaskMetadataEvent(
                        session_id=self.id, metadata=mt, is_partial=mt.is_partial, timestamp=msg_ts
                    )
                case message.DeveloperMessage() as dm:
                    yield events.DeveloperMessageEvent(session_id=self.id, item=dm, timestamp=msg_ts)
                case message.StreamErrorItem():
                    pass  # skip errors during replay
                case message.InterruptEntry() as interrupt:
                    prev_turn_interrupted = True
                    yield events.InterruptEvent(
                        session_id=self.id,
                        show_notice=interrupt.show_notice,
                        timestamp=msg_ts,
                    )
                case message.RewindEntry() as be:
                    yield events.RewindEvent(
                        session_id=self.id,
                        checkpoint_id=be.checkpoint_id,
                        note=be.note,
                        rationale=be.rationale,
                        original_user_message=be.original_user_message,
                        messages_discarded=None,
                        timestamp=msg_ts,
                    )
                case message.CompactionEntry() as ce:
                    yield events.CompactionStartEvent(session_id=self.id, reason="threshold", timestamp=msg_ts)
                    yield events.CompactionEndEvent(
                        session_id=self.id,
                        reason="threshold",
                        aborted=False,
                        will_retry=False,
                        tokens_before=ce.tokens_before,
                        kept_from_index=ce.first_kept_index,
                        summary=ce.summary,
                        kept_items_brief=ce.kept_items_brief,
                        timestamp=msg_ts,
                    )
                case message.CacheHitRateEntry() as cr:
                    yield events.CacheHitRateEvent(
                        session_id=self.id,
                        cache_hit_rate=cr.cache_hit_rate,
                        cached_tokens=cr.cached_tokens,
                        prev_turn_input_tokens=cr.prev_turn_input_tokens,
                        timestamp=msg_ts,
                    )
                case message.AwaySummaryEntry() as aw:
                    if had_any_turn:
                        yield from _flush_task_finish(msg_ts)
                    yield events.AwaySummaryEvent(session_id=self.id, text=aw.text, timestamp=msg_ts)
                case message.PromptSuggestionEntry() as ps:
                    yield events.PromptSuggestionReadyEvent(session_id=self.id, text=ps.text, timestamp=msg_ts)
                case message.SpawnSubAgentEntry() as sa:
                    yield from self._iter_sub_agent_history_by_id(sa.session_id, seen_sub_agent_sessions)
                case message.SystemMessage():
                    pass
            prev_item = it

        # Flush any remaining pending tool calls (e.g., from aborted or incomplete sessions)
        if pending_tool_calls:
            yield from pending_tool_calls.values()
            pending_tool_calls.clear()

        if emit_finish and had_any_turn and task_finish_pending:
            yield from _flush_task_finish(msg_ts)

    def _iter_sub_agent_history_by_id(
        self, session_id: str, seen_sub_agent_sessions: set[str]
    ) -> Iterable[events.ReplayEventUnion]:
        if not session_id or session_id == self.id:
            return
        if session_id in seen_sub_agent_sessions:
            return
        seen_sub_agent_sessions.add(session_id)
        try:
            sub_session = Session.load(session_id, work_dir=self.work_dir)
        except (OSError, json.JSONDecodeError, ValueError):
            return
        yield from sub_session.get_history_item(emit_finish=sub_session._has_task_completed())

    def _iter_sub_agent_history(
        self, tool_result: message.ToolResultMessage, seen_sub_agent_sessions: set[str]
    ) -> Iterable[events.ReplayEventUnion]:
        ui_extra = tool_result.ui_extra
        if not isinstance(ui_extra, SessionIdUIExtra):
            return
        yield from self._iter_sub_agent_history_by_id(ui_extra.session_id, seen_sub_agent_sessions)

    class SessionMetaBrief(BaseModel):
        id: str
        created_at: float
        updated_at: float
        work_dir: str
        path: str
        title: str | None = None
        user_messages: list[str] = []
        messages_count: int = -1
        model_name: str | None = None
        session_state: SessionRuntimeState | None = None
        archived: bool = False

    @classmethod
    def list_sessions(cls, work_dir: Path) -> list[SessionMetaBrief]:
        store = get_store_for_path(work_dir)

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
            data = read_json_dict(meta_path)
            if data is None:
                continue
            if data.get("sub_agent_state") is not None:
                continue

            sid = str(data.get("id", meta_path.parent.name))
            created = float(data.get("created_at", meta_path.stat().st_mtime))
            updated = float(data.get("updated_at", meta_path.stat().st_mtime))
            session_work_dir = str(data.get("work_dir", ""))
            title = data.get("title") if isinstance(data.get("title"), str) else None

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
            session_state_raw = data.get("session_state")
            session_state = parse_session_state(session_state_raw)
            archived_raw = data.get("archived")
            archived = archived_raw if isinstance(archived_raw, bool) else False

            items.append(
                Session.SessionMetaBrief(
                    id=sid,
                    created_at=created,
                    updated_at=updated,
                    work_dir=session_work_dir,
                    path=str(meta_path),
                    title=title,
                    user_messages=user_messages,
                    messages_count=messages_count,
                    model_name=model_name,
                    session_state=session_state,
                    archived=archived,
                )
            )

        items.sort(key=lambda d: d.updated_at, reverse=True)
        return items

    @classmethod
    def find_sessions_by_prefix(cls, prefix: str, work_dir: Path) -> list[str]:
        """Find main session IDs matching a prefix.

        Args:
            prefix: Session ID prefix to match.
            work_dir: Project working directory.

        Returns:
            List of matching session IDs, sorted alphabetically.
        """
        prefix = (prefix or "").strip().lower()
        if not prefix:
            return []

        store = get_store_for_path(work_dir)
        matches: set[str] = set()

        for meta_path in store.iter_meta_files():
            data = read_json_dict(meta_path)
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
    def shortest_unique_prefix(cls, session_id: str, work_dir: Path, min_length: int = 4) -> str:
        """Find the shortest unique prefix for a session ID.

        Args:
            session_id: The session ID to find prefix for.
            work_dir: Project working directory.
            min_length: Minimum prefix length (default 4).

        Returns:
            The shortest prefix that uniquely identifies this session.
        """
        store = get_store_for_path(work_dir)
        other_ids: list[str] = []

        for meta_path in store.iter_meta_files():
            data = read_json_dict(meta_path)
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
