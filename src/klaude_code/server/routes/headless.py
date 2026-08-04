"""Headless command surface: the server side of `klaude run/ps/brief/wait/output/send/respond/kill`.

TARGET resolution, the queued/running/waiting_input/idle/failed state model,
and bounded serialization all live here so every CLI client stays thin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import message, op, user_interaction
from klaude_code.protocol.message import UserInputPayload
from klaude_code.protocol.sub_agent import get_all_names
from klaude_code.server.headless import HeadlessRuntime, format_tool_call_activity
from klaude_code.server.session_index import SessionSummary
from klaude_code.server.session_state import derive_session_state_from_snapshot, live_descendant_session_ids
from klaude_code.server.state import ServerAppState, get_server_state
from klaude_code.session.session import Session

router = APIRouter(prefix="/api/headless", tags=["headless"])
STATE_DEP: Final = Depends(get_server_state)
STATES_QUERY: Final = Query(None, alias="state")

type HeadlessState = Literal["queued", "running", "waiting_input", "idle", "failed"]

ACTIVE_STATES: Final = ("queued", "running", "waiting_input")
VALID_STATES: Final = ("queued", "running", "waiting_input", "idle", "failed")


# -- shared helpers --


def _require_headless(state: ServerAppState) -> HeadlessRuntime:
    if state.headless is None:
        raise HTTPException(status_code=503, detail="headless runtime is not available")
    return state.headless


def _load_summaries(state: ServerAppState) -> list[SessionSummary]:
    if state.session_live is None:
        raise HTTPException(status_code=503, detail="session index is not available")
    state.session_live.index.reload()
    return state.session_live.index.list_all()


def _resolve_target(summaries: list[SessionSummary], target: str) -> SessionSummary:
    """Resolve a TARGET (session id, unique id prefix, or `run --name`)."""
    needle = target.strip()
    if not needle:
        raise HTTPException(status_code=400, detail="empty target")

    by_id = {summary.id: summary for summary in summaries}
    if needle in by_id:
        return by_id[needle]

    name_matches = [summary for summary in summaries if summary.name == needle]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        active = [summary for summary in name_matches if not summary.archived]
        if len(active) == 1:
            return active[0]
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"ambiguous target '{target}'",
                "candidates": [summary.id for summary in name_matches],
            },
        )

    prefix = needle.lower()
    prefix_matches = [summary for summary in summaries if summary.id.lower().startswith(prefix)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"ambiguous target '{target}'",
                "candidates": [summary.id for summary in prefix_matches],
            },
        )
    raise HTTPException(status_code=404, detail=f"no session matches target '{target}'")


def _headless_state(state: ServerAppState, headless: HeadlessRuntime, session_id: str) -> HeadlessState:
    if headless.is_queued(session_id):
        return "queued"
    actor = state.runtime.session_registry.get_session_actor(session_id)
    if actor is not None:
        derived = derive_session_state_from_snapshot(actor.snapshot())
        if derived == "waiting_user_input":
            return "waiting_input"
        if derived == "running":
            # A sub-agent parked on an interaction stalls the whole tree; the
            # caller polls the parent, so bubble the state up (§7 closed loop).
            if _pending_requests(state, session_id):
                return "waiting_input"
            return "running"
    if headless.is_running(session_id) or headless.turn_start_pending(session_id):
        return "running"
    if headless.tracker.is_failed(session_id):
        return "failed"
    return "idle"


def _pending_requests(state: ServerAppState, session_id: str) -> list[PendingUserInteractionRequest]:
    """Pending requests of the session and its live sub-agent descendants."""
    registry = state.runtime.session_registry
    requests: list[PendingUserInteractionRequest] = []
    for target_id in (session_id, *sorted(live_descendant_session_ids(registry, session_id))):
        actor = registry.get_session_actor(target_id)
        if actor is not None:
            requests.extend(actor.pending_requests_snapshot())
    return requests


def serialize_pending_request(request: PendingUserInteractionRequest) -> dict[str, Any]:
    payload = request.payload
    if isinstance(payload, user_interaction.AskUserQuestionRequestPayload):
        first = payload.questions[0] if payload.questions else None
        return {
            "request_id": request.request_id,
            "type": "question",
            "prompt": first.question if first is not None else "",
            "options": [
                {"index": index, "label": option.label, "description": option.description}
                for index, option in enumerate(first.options if first is not None else [], start=1)
            ],
            "multi_select": first.multi_select if first is not None else False,
            "question_count": len(payload.questions),
        }
    return {
        "request_id": request.request_id,
        "type": "choice",
        "prompt": payload.question,
        "options": [
            {"index": index, "label": option.label, "description": option.description}
            for index, option in enumerate(payload.options, start=1)
        ],
        "multi_select": False,
        "question_count": 1,
    }


def _activity_label(
    state: ServerAppState,
    headless: HeadlessRuntime,
    session_id: str,
    session_state: HeadlessState,
) -> str | None:
    if session_state == "queued":
        return "queued"
    if session_state == "running":
        current = headless.tracker.current_tool_call(session_id)
        if current is not None:
            return format_tool_call_activity(current[0], current[1])
        return "thinking"
    if session_state == "waiting_input":
        pending = _pending_requests(state, session_id)
        if pending:
            info = serialize_pending_request(pending[0])
            prompt = str(info.get("prompt") or "")
            prompt = " ".join(prompt.split())
            if len(prompt) > 60:
                prompt = prompt[:59] + "…"
            return f"{info['type']}: {prompt}"
        return "waiting for input"
    return None


def _serialize_row(
    state: ServerAppState,
    headless: HeadlessRuntime,
    summary: SessionSummary,
) -> dict[str, Any]:
    session_state = _headless_state(state, headless, summary.id)
    row: dict[str, Any] = {
        "id": summary.id,
        "name": summary.name,
        "group": summary.group,
        "agent_type": summary.agent_type,
        "spawn_kind": summary.spawn_kind,
        "parent_session_id": summary.parent_session_id,
        "state": session_state,
        "model": summary.model_config_name or summary.model_name,
        "work_dir": summary.work_dir,
        "title": summary.title,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "archived": summary.archived,
        "activity": _activity_label(state, headless, summary.id, session_state),
        # This remains true across the idle teardown window between queued
        # follow-up turns. CLI wait uses it as the stable server contract.
        "pending": headless.has_pending(summary.id),
    }
    if session_state == "waiting_input":
        pending = _pending_requests(state, summary.id)
        if pending:
            row["pending_request"] = serialize_pending_request(pending[0])
    return row


def _load_session_for_read(state: ServerAppState, session_id: str, work_dir: Path) -> Session:
    """Prefer the in-memory session when it is ahead of disk (unflushed items)."""
    try:
        disk_session = Session.load(session_id, work_dir=work_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to load session: {exc}") from exc
    actor = state.runtime.session_registry.get_session_actor(session_id)
    agent = actor.get_agent() if actor is not None else None
    if agent is not None and len(agent.session.conversation_history) >= len(disk_session.conversation_history):
        return agent.session
    return disk_session


def _last_assistant_text(history: list[message.HistoryEvent]) -> str:
    for item in reversed(history):
        if isinstance(item, message.AssistantMessage):
            text = message.join_text_parts(item.parts)
            if text.strip():
                return text
    return ""


def _render_transcript_items(history: list[message.HistoryEvent]) -> list[str]:
    blocks: list[str] = []
    for item in history:
        if isinstance(item, message.UserMessage):
            text = message.join_text_parts(item.parts)
            if text.strip():
                blocks.append(f"user> {text}")
        elif isinstance(item, message.AssistantMessage):
            text = message.join_text_parts(item.parts)
            if text.strip():
                blocks.append(text)
            for part in item.parts:
                if isinstance(part, message.ToolCallPart):
                    blocks.append(f"[{format_tool_call_activity(part.tool_name, part.arguments_json, max_len=120)}]")
        elif isinstance(item, message.ToolResultMessage):
            result = " ".join(item.output_text.split())
            if len(result) > 200:
                result = result[:199] + "…"
            if result:
                blocks.append(f"  -> {result}")
    return blocks


def _render_turns(history: list[message.HistoryEvent], turns: int) -> str:
    """Render the last N user+assistant turns as plain text."""
    turn_starts = [
        index
        for index, item in enumerate(history)
        if isinstance(item, message.UserMessage) and item.source != "bash_mode"
    ]
    if not turn_starts:
        return "\n\n".join(_render_transcript_items(history))
    start = turn_starts[-turns] if turns <= len(turn_starts) else 0
    return "\n\n".join(_render_transcript_items(history[start:]))


# -- run --


class HeadlessRunRequest(BaseModel):
    prompt: str
    work_dir: str | None = None
    model: str | None = None
    agent: str = "main"
    name: str | None = None
    group: str | None = None
    approval: Literal["hold", "auto", "deny"] = "hold"


def _resolve_run_model(model: str | None, agent: str) -> str | None:
    """Resolve the model alias to persist on the session; None inherits the server default."""
    from klaude_code.config import load_config

    try:
        config = load_config()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to load config: {exc}") from exc

    if model is not None:
        try:
            candidates = config.iter_model_config_candidates(model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unknown model '{model}': {exc}") from exc
        if not candidates:
            diagnosis = config.diagnose_model(model)
            raise HTTPException(status_code=400, detail=f"model '{model}' is unavailable ({diagnosis.detail})")
        return model

    if agent != "main":
        preference = config.sub_agent_models.get(agent)
        if preference is not None:
            if isinstance(preference, str):
                return preference
            try:
                return config.get_first_available_model(preference)
            except ValueError:
                return None
    return None


@router.post("/run")
async def run_headless(payload: HeadlessRunRequest, state: ServerAppState = STATE_DEP) -> dict[str, Any]:
    headless = _require_headless(state)

    prompt = payload.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is empty")

    work_dir = Path(payload.work_dir).expanduser() if payload.work_dir else state.work_dir
    if not work_dir.exists() or not work_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"work_dir does not exist: {work_dir}")
    work_dir = work_dir.resolve()

    agent = payload.agent.strip() or "main"
    known_agents = ["main", *get_all_names()]
    if agent not in known_agents:
        raise HTTPException(
            status_code=400,
            detail={"message": f"unknown agent type '{agent}'", "agent_types": known_agents},
        )

    name = payload.name.strip() if payload.name else None
    if name is not None:
        summaries = _load_summaries(state)
        taken = any(summary.name == name and not summary.archived for summary in summaries)
        if taken:
            raise HTTPException(status_code=409, detail=f"name '{name}' is already used by an active session")

    resolved_model = _resolve_run_model(payload.model, agent)

    session = Session.create(id=uuid4().hex, work_dir=work_dir)
    session.name = name
    session.group = payload.group.strip() if payload.group else None
    session.agent_type = agent
    session.spawn_kind = "headless"
    session.approval_policy = payload.approval
    session.model_config_name = resolved_model
    session.ensure_meta_exists()

    try:
        run_state = await headless.spawn(
            session_id=session.id,
            prompt=UserInputPayload(text=prompt),
            work_dir=work_dir,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to start agent: {exc}") from exc

    return {"session_id": session.id, "name": name, "state": run_state}


# -- ps --


@router.get("/sessions")
async def list_headless_sessions(
    targets: str | None = None,
    group: str | None = None,
    dir: str | None = None,
    states: list[str] | None = STATES_QUERY,
    limit: int = 20,
    include_archived: bool = False,
    include_children: bool = False,
    state: ServerAppState = STATE_DEP,
) -> dict[str, Any]:
    headless = _require_headless(state)
    summaries = _load_summaries(state)

    if states:
        invalid = [item for item in states if item not in VALID_STATES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"invalid state filter {invalid}; valid states: {', '.join(VALID_STATES)}",
            )

    selected: list[SessionSummary]
    if targets:
        target_list = [part for part in (piece.strip() for piece in targets.split(",")) if part]
        seen: set[str] = set()
        selected = []
        for target in target_list:
            summary = _resolve_target(summaries, target)
            if summary.id not in seen:
                seen.add(summary.id)
                selected.append(summary)
    else:
        selected = summaries

    if group:
        selected = [summary for summary in selected if summary.group == group]
    if dir:
        dir_path = str(Path(dir).expanduser().resolve())
        selected = [
            summary
            for summary in selected
            if summary.work_dir == dir_path or summary.work_dir.startswith(dir_path.rstrip("/") + "/")
        ]
    if not include_archived and not targets:
        selected = [summary for summary in selected if not summary.archived]
    if not include_children and not targets:
        selected = [summary for summary in selected if summary.parent_session_id is None]

    rows = [_serialize_row(state, headless, summary) for summary in selected]
    if states:
        rows = [row for row in rows if row["state"] in states]

    rows.sort(key=lambda row: (0 if row["state"] in ACTIVE_STATES else 1, -float(row["updated_at"])))
    if limit > 0 and not targets:
        if include_children:
            # The limit counts top-level sessions; their children ride along.
            row_ids = {row["id"] for row in rows}
            roots = [row for row in rows if not row.get("parent_session_id") or row["parent_session_id"] not in row_ids]
            kept_roots = {row["id"] for row in roots[:limit]}
            rows = [row for row in rows if row["id"] in kept_roots or row.get("parent_session_id") in kept_roots]
        else:
            rows = rows[:limit]
    return {"sessions": rows}


# -- brief --


@router.get("/sessions/{target}/brief")
async def get_headless_brief(target: str, state: ServerAppState = STATE_DEP) -> dict[str, Any]:
    headless = _require_headless(state)
    summaries = _load_summaries(state)
    summary = _resolve_target(summaries, target)
    row = _serialize_row(state, headless, summary)

    session = _load_session_for_read(state, summary.id, Path(summary.work_dir))
    usage = session.last_request_usage
    current_tool = headless.tracker.current_tool_call(summary.id)

    row.update(
        {
            "todos": summary.todos,
            "file_change_summary": summary.file_change_summary,
            "approval_policy": summary.approval_policy,
            "last_assistant_message": _last_assistant_text(session.conversation_history),
            "current_tool_call": (
                format_tool_call_activity(current_tool[0], current_tool[1], max_len=200)
                if current_tool is not None
                else None
            ),
            "usage": (
                {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cached_tokens": usage.cached_tokens,
                    "context_size": usage.context_size,
                    "context_limit": usage.context_limit,
                }
                if usage is not None
                else None
            ),
        }
    )
    pending = _pending_requests(state, summary.id)
    if pending:
        row["pending_request"] = serialize_pending_request(pending[0])
    return row


# -- output --


@router.get("/sessions/{target}/output")
async def get_headless_output(
    target: str,
    turns: int | None = None,
    transcript: bool = False,
    state: ServerAppState = STATE_DEP,
) -> dict[str, Any]:
    headless = _require_headless(state)
    summaries = _load_summaries(state)
    summary = _resolve_target(summaries, target)

    session = _load_session_for_read(state, summary.id, Path(summary.work_dir))
    if transcript:
        output = "\n\n".join(_render_transcript_items(session.conversation_history))
    elif turns is not None and turns > 0:
        output = _render_turns(session.conversation_history, turns)
    else:
        output = _last_assistant_text(session.conversation_history)

    result: dict[str, Any] = {
        "id": summary.id,
        "name": summary.name,
        "state": _headless_state(state, headless, summary.id),
        "output": output,
        "pending": headless.has_pending(summary.id),
    }
    pending = _pending_requests(state, summary.id)
    if pending:
        result["pending_request"] = serialize_pending_request(pending[0])
    return result


# -- send --


class HeadlessSendRequest(BaseModel):
    text: str
    steer: bool = False


@router.post("/sessions/{target}/send")
async def send_headless_message(
    target: str,
    payload: HeadlessSendRequest,
    state: ServerAppState = STATE_DEP,
) -> dict[str, Any]:
    headless = _require_headless(state)
    summaries = _load_summaries(state)
    summary = _resolve_target(summaries, target)

    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message text is empty")
    if headless.is_queued(summary.id) and (not payload.steer or not headless.can_replace_queued_for_steer(summary.id)):
        raise HTTPException(status_code=409, detail="session is queued and has not started yet; wait for it first")

    user_input = UserInputPayload(text=text)
    try:
        if payload.steer:
            mode = await headless.steer(
                session_id=summary.id,
                prompt=user_input,
                work_dir=Path(summary.work_dir),
            )
        else:
            mode = await headless.send(
                session_id=summary.id,
                prompt=user_input,
                work_dir=Path(summary.work_dir),
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to schedule message: {exc}") from exc
    return {"session_id": summary.id, "mode": mode, "pending": True}


# -- respond --


class HeadlessRespondRequest(BaseModel):
    action: Literal["approve", "deny", "option", "text"]
    option: int | None = None
    text: str | None = None


def _build_interaction_response(
    request: PendingUserInteractionRequest,
    payload: HeadlessRespondRequest,
) -> user_interaction.UserInteractionResponse:
    interaction = request.payload

    if payload.action == "deny":
        return user_interaction.UserInteractionResponse(status="cancelled", payload=None)

    if payload.action == "approve":
        if request.source == "approval":
            return user_interaction.UserInteractionResponse(status="submitted", payload=None)
        raise HTTPException(
            status_code=400,
            detail="pending request is not a permission request; answer it with --option N or --text",
        )

    if payload.action == "option":
        if payload.option is None or payload.option < 1:
            raise HTTPException(status_code=400, detail="--option requires a 1-based option number")
        if isinstance(interaction, user_interaction.AskUserQuestionRequestPayload):
            if not interaction.questions:
                raise HTTPException(status_code=409, detail="pending request has no questions")
            question = interaction.questions[0]
            if payload.option > len(question.options):
                raise HTTPException(status_code=400, detail=f"option out of range (1-{len(question.options)})")
            answer = user_interaction.AskUserQuestionAnswer(
                question_id=question.id,
                selected_option_ids=[question.options[payload.option - 1].id],
            )
            return user_interaction.UserInteractionResponse(
                status="submitted",
                payload=user_interaction.AskUserQuestionResponsePayload(answers=[answer]),
            )
        if payload.option > len(interaction.options):
            raise HTTPException(status_code=400, detail=f"option out of range (1-{len(interaction.options)})")
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.OperationSelectResponsePayload(
                selected_option_id=interaction.options[payload.option - 1].id
            ),
        )

    # action == "text"
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="--text requires a non-empty answer")
    if isinstance(interaction, user_interaction.AskUserQuestionRequestPayload):
        if not interaction.questions:
            raise HTTPException(status_code=409, detail="pending request has no questions")
        question = interaction.questions[0]
        answer = user_interaction.AskUserQuestionAnswer(
            question_id=question.id,
            selected_option_ids=[],
            other_text=payload.text.strip(),
        )
        return user_interaction.UserInteractionResponse(
            status="submitted",
            payload=user_interaction.AskUserQuestionResponsePayload(answers=[answer]),
        )
    raise HTTPException(status_code=400, detail="pending request is a choice; pick it with --option N")


@router.post("/sessions/{target}/respond")
async def respond_headless(
    target: str,
    payload: HeadlessRespondRequest,
    state: ServerAppState = STATE_DEP,
) -> dict[str, Any]:
    _ = _require_headless(state)
    summaries = _load_summaries(state)
    summary = _resolve_target(summaries, target)

    pending = _pending_requests(state, summary.id)
    if not pending:
        raise HTTPException(status_code=409, detail="session has no pending interaction request")
    request = pending[0]
    response = _build_interaction_response(request, payload)

    await state.runtime.submit(
        op.UserInteractionRespondOperation(
            # The request may be parked on a sub-agent session under the
            # target; route the response to its owning actor.
            session_id=request.session_id,
            request_id=request.request_id,
            response=response,
        )
    )
    return {"ok": True, "session_id": summary.id, "request_id": request.request_id, "status": response.status}


# -- kill --


@router.post("/sessions/{target}/interrupt")
async def interrupt_headless(target: str, state: ServerAppState = STATE_DEP) -> dict[str, Any]:
    headless = _require_headless(state)
    summaries = _load_summaries(state)
    summary = _resolve_target(summaries, target)

    cancelled_queued = await headless.prepare_interrupt(summary.id, Path(summary.work_dir))

    actor = state.runtime.session_registry.get_session_actor(summary.id)
    if actor is None or actor.snapshot().is_idle:
        if cancelled_queued:
            return {"ok": True, "session_id": summary.id, "was": "queued"}
        return {"ok": True, "session_id": summary.id, "was": "idle"}

    await state.runtime.submit(op.InterruptOperation(session_id=summary.id))
    return {"ok": True, "session_id": summary.id, "was": "running"}
