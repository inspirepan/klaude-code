"""Read-only web viewer REST surface (`/api/web/...`).

The ledger endpoints read `events.jsonl` straight from disk, so most tests
here lay a session down by hand (meta.json + jsonl lines) and never start an
agent — that cold path is exactly what the viewer uses for old sessions.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from klaude_code.const import ProjectPaths, project_key_from_path
from klaude_code.prompts.messages import (
    EMPTY_RESPONSE_CONTINUATION_PROMPT,
    build_stream_error_continuation_prompt,
)
from klaude_code.prompts.sub_agents import FORK_CONTEXT_GENERAL_PROMPT, FORK_CONTEXT_WITH_ROLE_PROMPT
from klaude_code.protocol import message
from klaude_code.protocol.models import TaskMetadataItem
from klaude_code.server.routes import web_api
from klaude_code.session.codec import encode_jsonl_line

from .conftest import AppEnv

type Line = message.HistoryEvent | str


def _user(text: str) -> message.UserMessage:
    return message.UserMessage(parts=message.text_parts_from_str(text))


def _assistant(text: str) -> message.AssistantMessage:
    return message.AssistantMessage(parts=message.text_parts_from_str(text))


def _bash(command: str) -> message.UserMessage:
    """A bash-mode echo, as `agent/bash_mode.py` writes it."""
    return message.UserMessage(
        parts=message.text_parts_from_str(f"<bash-input>{command}</bash-input>"),
        source="bash_mode",
    )


def _ordinals(payload: dict[str, Any]) -> list[tuple[int, int, int | None, bool | None]]:
    return [(row["line_index"], row["turn_index"], row["step_index"], row["auto"]) for row in payload["rows"]]


def _write_session(
    work_dir: Path,
    session_id: str,
    lines: Sequence[Line],
    *,
    meta_extra: dict[str, Any] | None = None,
) -> Path:
    """Lay down a cold session on disk: meta.json plus raw jsonl lines."""
    paths = ProjectPaths(project_key=project_key_from_path(work_dir))
    session_dir = paths.session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    payload = "".join(line if isinstance(line, str) else encode_jsonl_line(line) for line in lines)
    paths.events_file(session_id).write_text(payload, encoding="utf-8")
    meta: dict[str, Any] = {
        "id": session_id,
        "work_dir": str(work_dir),
        "title": "cold session",
        "created_at": 1000.0,
        "updated_at": 2000.0,
        "model_name": "fake-model",
    }
    meta.update(meta_extra or {})
    paths.meta_file(session_id).write_text(json.dumps(meta), encoding="utf-8")
    return session_dir


def _history(app_env: AppEnv, session_id: str, **params: int | None) -> dict[str, Any]:
    response = app_env.client.get(f"/api/web/sessions/{session_id}/history", params=params)
    assert response.status_code == 200, response.text
    return dict(response.json())


# -- meta --


def test_meta_reports_disk_fields_for_a_cold_session(app_env: AppEnv) -> None:
    session_id = "cold0001"
    _write_session(app_env.work_dir, session_id, [_user("hi"), _assistant("hello")])

    payload = app_env.client.get(f"/api/web/sessions/{session_id}/meta").json()

    assert payload == {
        "session_id": session_id,
        "title": "cold session",
        "work_dir": str(app_env.work_dir),
        "model": "fake-model",
        "parent_session_id": None,
        "created_at": 1000.0,
        "updated_at": 2000.0,
        "state": "completed",
        "loaded": False,
        "line_count": 2,
    }
    # Reading a cold session must not spin up an agent for it.
    assert not app_env.runtime.session_registry.has_session_actor(session_id)


def test_meta_prefers_the_model_config_name_and_reports_the_parent(app_env: AppEnv) -> None:
    session_id = "cold0002"
    _write_session(
        app_env.work_dir,
        session_id,
        [],
        meta_extra={"model_config_name": "sonnet", "parent_session_id": "parent01"},
    )

    payload = app_env.client.get(f"/api/web/sessions/{session_id}/meta").json()

    assert payload["model"] == "sonnet"
    assert payload["parent_session_id"] == "parent01"
    assert payload["line_count"] == 0


def test_meta_reports_loaded_for_a_session_with_an_actor(app_env: AppEnv) -> None:
    session_id = app_env.create_session()

    payload = app_env.client.get(f"/api/web/sessions/{session_id}/meta").json()

    assert payload["loaded"] is True
    assert payload["work_dir"] == str(app_env.work_dir)
    assert payload["state"] in {"idle", "completed", "running"}


def test_meta_of_an_unknown_session_is_404(app_env: AppEnv) -> None:
    assert app_env.client.get("/api/web/sessions/nope/meta").status_code == 404


# -- history paging --


def test_history_returns_the_tail_page_by_default(app_env: AppEnv) -> None:
    session_id = "page0001"
    _write_session(app_env.work_dir, session_id, [_user(f"m{i}") for i in range(10)])

    payload = _history(app_env, session_id, limit=3)

    assert payload["session_id"] == session_id
    assert payload["line_count"] == 10
    assert [row["line_index"] for row in payload["rows"]] == [7, 8, 9]
    assert payload["has_more"] is True
    assert payload["next_before_line"] == 7
    assert payload["rows"][0]["entry"]["type"] == "UserMessage"
    assert payload["rows"][0]["status"] == "active"
    assert payload["rows"][0]["dropped_by"] is None


def test_history_before_line_walks_back_to_the_beginning(app_env: AppEnv) -> None:
    session_id = "page0002"
    _write_session(app_env.work_dir, session_id, [_user(f"m{i}") for i in range(5)])

    first = _history(app_env, session_id, limit=2)
    second = _history(app_env, session_id, before_line=first["next_before_line"], limit=2)
    third = _history(app_env, session_id, before_line=second["next_before_line"], limit=2)

    assert [row["line_index"] for row in first["rows"]] == [3, 4]
    assert [row["line_index"] for row in second["rows"]] == [1, 2]
    assert second["has_more"] is True
    assert [row["line_index"] for row in third["rows"]] == [0]
    assert third["has_more"] is False
    assert third["next_before_line"] == 0
    assert _history(app_env, session_id, before_line=0)["rows"] == []


def test_history_after_line_returns_the_tail_increment(app_env: AppEnv) -> None:
    session_id = "page0003"
    _write_session(app_env.work_dir, session_id, [_user(f"m{i}") for i in range(6)])

    payload = _history(app_env, session_id, after_line=1, limit=2)

    assert [row["line_index"] for row in payload["rows"]] == [2, 3]
    assert payload["has_more"] is True
    assert payload["next_before_line"] is None
    tail = _history(app_env, session_id, after_line=3)
    assert [row["line_index"] for row in tail["rows"]] == [4, 5]
    assert tail["has_more"] is False
    assert _history(app_env, session_id, after_line=5)["rows"] == []


def test_history_rejects_both_paging_anchors(app_env: AppEnv) -> None:
    session_id = "page0004"
    _write_session(app_env.work_dir, session_id, [_user("m")])

    response = app_env.client.get(f"/api/web/sessions/{session_id}/history", params={"before_line": 1, "after_line": 0})
    assert response.status_code == 400


def test_history_clamps_the_limit(app_env: AppEnv) -> None:
    session_id = "page0005"
    _write_session(app_env.work_dir, session_id, [_user(f"m{i}") for i in range(3)])

    assert len(_history(app_env, session_id, limit=99_999)["rows"]) == 3
    # Below the floor the page still carries one row instead of none.
    assert [row["line_index"] for row in _history(app_env, session_id, limit=0)["rows"]] == [2]
    assert web_api.MAX_HISTORY_LIMIT == 2000
    assert web_api.DEFAULT_HISTORY_LIMIT == 500


def test_history_of_an_unknown_session_is_404(app_env: AppEnv) -> None:
    assert app_env.client.get("/api/web/sessions/nope/history").status_code == 404


def test_history_keeps_undecodable_lines_as_null_entries(app_env: AppEnv) -> None:
    session_id = "page0006"
    _write_session(
        app_env.work_dir,
        session_id,
        [_user("first"), "{not json at all\n", '{"type": "NoSuchEntry", "data": {}}\n', _user("last")],
    )

    rows = _history(app_env, session_id)["rows"]

    assert [(row["line_index"], row["status"]) for row in rows] == [
        (0, "active"),
        (1, "unknown"),
        (2, "unknown"),
        (3, "active"),
    ]
    assert rows[1]["entry"] is None
    assert rows[2]["entry"] is None
    assert rows[3]["entry"]["data"]["parts"][0]["text"] == "last"


def test_history_reports_retract_compaction_and_sidecar_statuses(app_env: AppEnv) -> None:
    session_id = "page0007"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            _user("kept"),
            _assistant("reply"),
            TaskMetadataItem(),
            _user("oops"),
            message.RetractEntry(retracted_text="oops", retracted_line=3),
            message.CompactionEntry(summary="so far", first_kept_index=3, first_kept_line=6),
            _user("after compaction"),
        ],
    )

    payload = _history(app_env, session_id)
    statuses = [(row["line_index"], row["status"], row["dropped_by"]) for row in payload["rows"]]

    assert statuses == [
        (0, "compacted", 5),
        (1, "compacted", 5),
        (2, "sidecar", None),
        (3, "retracted", 4),
        # Marker lines stay in the active list, so the compaction prefix
        # covers the retract entry too; they take no ledger row of their own.
        (4, "compacted", 5),
        (5, "active", None),
        (6, "active", None),
    ]
    assert payload["rows"][4]["entry"]["type"] == "RetractEntry"


def test_history_entry_matches_the_on_disk_line(app_env: AppEnv) -> None:
    session_id = "page0008"
    entry = message.CompactionEntry(summary="s", first_kept_index=1, first_kept_line=1)
    _write_session(app_env.work_dir, session_id, [entry])

    row = _history(app_env, session_id)["rows"][0]

    assert row["entry"] == json.loads(encode_jsonl_line(entry))


# -- turn / step ordinals --


def test_history_numbers_turns_and_steps_across_the_file(app_env: AppEnv) -> None:
    session_id = "turn0001"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            # A preamble line ahead of the first human message: turn 0.
            _assistant("preamble"),
            _user("q1"),
            _assistant("a1"),
            _assistant("a2"),
            _user("q2"),
            _assistant("a3"),
        ],
    )

    payload = _history(app_env, session_id)

    assert _ordinals(payload) == [
        (0, 0, 1, None),
        (1, 1, None, False),
        (2, 1, 1, None),
        (3, 1, 2, None),
        (4, 2, None, False),
        (5, 2, 1, None),
    ]
    assert payload["turn_count"] == 2


def test_history_turn_count_is_zero_without_a_human_message(app_env: AppEnv) -> None:
    session_id = "turn0002"
    _write_session(app_env.work_dir, session_id, [_assistant("only me"), _bash("ls")])

    payload = _history(app_env, session_id)

    assert payload["turn_count"] == 0
    assert _ordinals(payload) == [(0, 0, 1, None), (1, 0, None, True)]


def test_history_flags_every_kind_of_runtime_injected_user_message(app_env: AppEnv) -> None:
    session_id = "turn0003"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            _user("typed by a person"),
            _bash("git status"),
            _user(EMPTY_RESPONSE_CONTINUATION_PROMPT),
            _user(build_stream_error_continuation_prompt("half an answer")),
            _user(f"<system-reminder>{FORK_CONTEXT_GENERAL_PROMPT}</system-reminder>"),
            _user(f"<system-reminder>{FORK_CONTEXT_WITH_ROLE_PROMPT}You review code.</system-reminder>"),
        ],
    )

    payload = _history(app_env, session_id)

    assert [row["auto"] for row in payload["rows"]] == [False, True, True, True, True, True]
    # None of the injected messages opens a turn of its own.
    assert [row["turn_index"] for row in payload["rows"]] == [1] * 6
    assert payload["turn_count"] == 1


def test_history_keeps_stepping_across_a_bash_mode_message(app_env: AppEnv) -> None:
    session_id = "turn0004"
    _write_session(
        app_env.work_dir,
        session_id,
        [_user("q1"), _assistant("a1"), _bash("ls"), _assistant("a2"), _user("q2"), _assistant("a3")],
    )

    assert _ordinals(_history(app_env, session_id)) == [
        (0, 1, None, False),
        (1, 1, 1, None),
        (2, 1, None, True),
        # The bash echo does not reset the step counter, only a human turn does.
        (3, 1, 2, None),
        (4, 2, None, False),
        (5, 2, 1, None),
    ]


def test_history_places_undecodable_lines_in_the_surrounding_turn(app_env: AppEnv) -> None:
    session_id = "turn0005"
    _write_session(
        app_env.work_dir,
        session_id,
        [_user("q1"), "{not json at all\n", _assistant("a1"), _user("q2"), '{"type": "NoSuchEntry", "data": {}}\n'],
    )

    assert _ordinals(_history(app_env, session_id)) == [
        (0, 1, None, False),
        (1, 1, None, None),
        (2, 1, 1, None),
        (3, 2, None, False),
        (4, 2, None, None),
    ]


def test_history_ordinals_are_absolute_across_pages(app_env: AppEnv) -> None:
    session_id = "turn0006"
    lines: list[Line] = []
    for turn in range(4):
        lines.extend([_user(f"q{turn}"), _assistant(f"a{turn}"), _assistant(f"a{turn}-more")])
    _write_session(app_env.work_dir, session_id, lines)

    whole = _history(app_env, session_id)
    tail = _history(app_env, session_id, limit=4)
    older = _history(app_env, session_id, before_line=tail["next_before_line"], limit=4)

    by_line = {row["line_index"]: (row["turn_index"], row["step_index"]) for row in whole["rows"]}
    assert by_line[9] == (4, None)
    assert by_line[11] == (4, 2)
    for page in (tail, older):
        assert page["turn_count"] == 4
        for row in page["rows"]:
            assert (row["turn_index"], row["step_index"]) == by_line[row["line_index"]], row["line_index"]


# -- local files --


@pytest.fixture
def temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stand in for the clipboard capture directory (`get_system_temp`)."""
    root = tmp_path / "systmp"
    root.mkdir()
    monkeypatch.setattr(web_api, "get_system_temp", lambda: str(root))
    return root


def _png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return path


def test_file_serves_images_from_the_three_allowed_roots(app_env: AppEnv, temp_root: Path) -> None:
    session_id = "file0001"
    _write_session(app_env.work_dir, session_id, [])
    paths = ProjectPaths(project_key=project_key_from_path(app_env.work_dir))
    candidates = [
        _png(app_env.work_dir / "shot.png"),
        _png(paths.images_dir(session_id) / "abc123.png"),
        _png(temp_root / "clipboard.png"),
    ]

    for candidate in candidates:
        response = app_env.client.get("/api/web/file", params={"session_id": session_id, "path": str(candidate)})
        assert response.status_code == 200, candidate
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content.startswith(b"\x89PNG")


def test_file_rejects_paths_outside_the_allowed_roots(app_env: AppEnv, tmp_path: Path) -> None:
    session_id = "file0002"
    _write_session(app_env.work_dir, session_id, [])
    outside = _png(tmp_path / "elsewhere" / "secret.png")

    direct = app_env.client.get("/api/web/file", params={"session_id": session_id, "path": str(outside)})
    escape = app_env.client.get(
        "/api/web/file",
        params={"session_id": session_id, "path": f"{app_env.work_dir}/../elsewhere/secret.png"},
    )

    assert direct.status_code == 403
    assert escape.status_code == 403


def test_file_rejects_a_symlink_that_escapes(app_env: AppEnv, tmp_path: Path) -> None:
    session_id = "file0003"
    _write_session(app_env.work_dir, session_id, [])
    outside = _png(tmp_path / "outside" / "secret.png")
    link = app_env.work_dir / "linked.png"
    link.symlink_to(outside)

    response = app_env.client.get("/api/web/file", params={"session_id": session_id, "path": str(link)})

    assert response.status_code == 403


def test_file_refuses_non_raster_types(app_env: AppEnv) -> None:
    session_id = "file0004"
    _write_session(app_env.work_dir, session_id, [])
    (app_env.work_dir / "notes.txt").write_text("secret", encoding="utf-8")
    (app_env.work_dir / "vector.svg").write_text("<svg onload='alert(1)'/>", encoding="utf-8")

    for name in ("notes.txt", "vector.svg"):
        response = app_env.client.get(
            "/api/web/file", params={"session_id": session_id, "path": str(app_env.work_dir / name)}
        )
        assert response.status_code == 415, name


def test_file_enforces_the_size_cap(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = "file0005"
    _write_session(app_env.work_dir, session_id, [])
    big = _png(app_env.work_dir / "big.png")
    monkeypatch.setattr(web_api, "MAX_FILE_BYTES", 4)

    response = app_env.client.get("/api/web/file", params={"session_id": session_id, "path": str(big)})

    assert response.status_code == 413


def test_file_missing_target_is_404(app_env: AppEnv) -> None:
    session_id = "file0006"
    _write_session(app_env.work_dir, session_id, [])

    response = app_env.client.get(
        "/api/web/file", params={"session_id": session_id, "path": str(app_env.work_dir / "gone.png")}
    )

    assert response.status_code == 404


def test_file_of_an_unknown_session_is_404(app_env: AppEnv) -> None:
    response = app_env.client.get("/api/web/file", params={"session_id": "nope", "path": "/tmp/x.png"})
    assert response.status_code == 404


def test_history_serves_the_llm_request_entry_as_a_sidecar_row(app_env: AppEnv) -> None:
    """The viewer's request dot rides the ledger like any other row."""
    session_id = "req00001"
    request = message.LLMRequestEntry(
        kind="compaction",
        label="fork",
        provider="anthropic",
        model="claude",
        options={"max_tokens": 8192},
        tool_call_count=0,
    )
    _write_session(
        app_env.work_dir,
        session_id,
        [
            _user("hi"),
            request,
            message.CompactionEntry(summary="s", first_kept_index=0, request_id=request.request_id),
        ],
    )

    rows = _history(app_env, session_id)["rows"]

    assert [row["status"] for row in rows] == ["active", "sidecar", "active"]
    assert rows[1]["entry"]["type"] == "LLMRequestEntry"
    assert rows[1]["entry"]["data"]["request_id"] == request.request_id
    assert rows[1]["entry"]["data"]["options"] == {"max_tokens": 8192}
    # The link the viewer joins on, with no positional guessing.
    assert rows[2]["entry"]["data"]["request_id"] == request.request_id
    # A sidecar never opens a turn or takes a step number.
    assert (rows[1]["turn_index"], rows[1]["step_index"], rows[1]["auto"]) == (1, None, None)


# -- sub-agent children --


def _spawn(child_id: str, sub_agent_type: str, desc: str, **extra: Any) -> message.SpawnSubAgentEntry:
    return message.SpawnSubAgentEntry(
        session_id=child_id,
        sub_agent_type=sub_agent_type,
        sub_agent_desc=desc,
        **extra,
    )


def _children(app_env: AppEnv, session_id: str) -> dict[str, Any]:
    response = app_env.client.get(f"/api/web/sessions/{session_id}/children")
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_children_report_the_type_and_description_the_parent_recorded(app_env: AppEnv) -> None:
    session_id = "kid00001"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            _user("review it"),
            _spawn("child001", "code-reviewer", "review the loader change", model="sonnet"),
            _assistant("done"),
        ],
    )

    payload = _children(app_env, session_id)

    assert payload["session_id"] == session_id
    assert len(payload["children"]) == 1
    child = payload["children"][0]
    assert child["session_id"] == "child001"
    assert child["sub_agent_type"] == "code-reviewer"
    assert child["sub_agent_desc"] == "review the loader change"
    assert child["model"] == "sonnet"
    assert child["line_index"] == 1
    # ISO 8601, the same shape the history endpoint encodes datetimes in.
    assert isinstance(child["created_at"], str) and "T" in child["created_at"]


def test_children_keep_file_order_and_dedupe_a_repeated_child_id(app_env: AppEnv) -> None:
    session_id = "kid00002"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            _spawn("child_b", "finder", "find the caller"),
            _spawn("child_a", "code-reviewer", "review it"),
            # A second row for a child already recorded: the first one wins.
            _spawn("child_b", "finder", "a later, weaker description"),
        ],
    )

    children = _children(app_env, session_id)["children"]

    assert [child["session_id"] for child in children] == ["child_b", "child_a"]
    assert children[0]["sub_agent_desc"] == "find the caller"
    assert [child["line_index"] for child in children] == [0, 1]


def test_children_of_a_session_that_spawned_none_is_empty(app_env: AppEnv) -> None:
    session_id = "kid00003"
    _write_session(app_env.work_dir, session_id, [_user("hi"), _assistant("hello")])

    assert _children(app_env, session_id) == {"session_id": session_id, "children": []}


def test_children_of_an_unknown_session_is_404(app_env: AppEnv) -> None:
    assert app_env.client.get("/api/web/sessions/nope/children").status_code == 404


# -- search --


def _search(app_env: AppEnv, session_id: str, q: str, **params: int) -> dict[str, Any]:
    response = app_env.client.get(f"/api/web/sessions/{session_id}/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_search_returns_every_matching_line_with_its_ledger_coordinates(app_env: AppEnv) -> None:
    session_id = "find0001"
    _write_session(
        app_env.work_dir,
        session_id,
        [_user("where is the widget"), _assistant("no widget here"), _user("unrelated")],
    )

    payload = _search(app_env, session_id, "widget")

    assert payload == {
        "session_id": session_id,
        "query": "widget",
        "terms": ["widget"],
        "matches": [
            {
                "line_index": 0,
                "turn_index": 1,
                "kind": "UserMessage",
                "status": "active",
                "snippet": "UserMessage where is the widget",
            },
            {
                "line_index": 1,
                "turn_index": 1,
                "kind": "AssistantMessage",
                "status": "active",
                "snippet": "AssistantMessage no widget here",
            },
        ],
        "total": 2,
        "truncated": False,
    }


def test_search_requires_every_term_and_ignores_case(app_env: AppEnv) -> None:
    session_id = "find0002"
    _write_session(
        app_env.work_dir,
        session_id,
        [_user("Alpha and Beta"), _user("alpha only"), _user("beta only")],
    )

    both = _search(app_env, session_id, "ALPHA   beta")

    assert both["terms"] == ["alpha", "beta"]
    assert [match["line_index"] for match in both["matches"]] == [0]
    # Each term on its own still matches the lines that carry it.
    assert [match["line_index"] for match in _search(app_env, session_id, "alpha")["matches"]] == [0, 1]
    assert [match["line_index"] for match in _search(app_env, session_id, "Beta")["matches"]] == [0, 2]


def test_search_reaches_every_text_bearing_entry_type(app_env: AppEnv) -> None:
    session_id = "find0003"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            _user("tokenuser"),
            message.AssistantMessage(parts=[message.ThinkingTextPart(text="tokenthinking")]),
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(
                        call_id="call-77",
                        tool_name="Grep",
                        arguments_json='{"pattern": "tokenargument"}',
                    )
                ]
            ),
            message.ToolResultMessage(
                call_id="call-77",
                tool_name="Grep",
                status="success",
                output_text="tokenresult",
            ),
            message.DeveloperMessage(parts=[message.TextPart(text="tokendeveloper")]),
            message.SideQuestionEntry(question="tokenquestion", answer="tokenanswer"),
            message.ForkSummaryEntry(
                summary="tokenfork", source_session_id="src", source_pivot_index=-1, source_message_count=0
            ),
            message.RewindEntry(
                checkpoint_id=1,
                note="tokennote",
                rationale="tokenrationale",
                reverted_from_index=0,
                original_user_message="x",
            ),
            message.CompactionEntry(summary="tokencompaction", first_kept_index=0, first_kept_line=9),
            _user("tail"),
        ],
    )

    expected = {
        "tokenuser": (0, "UserMessage"),
        "tokenthinking": (1, "AssistantMessage"),
        "tokenargument": (2, "AssistantMessage"),
        "call-77": (2, "AssistantMessage"),  # the tool call id, on both sides of the call
        "tokenresult": (3, "ToolResultMessage"),
        "tokendeveloper": (4, "DeveloperMessage"),
        "tokenquestion": (5, "SideQuestionEntry"),
        "tokenanswer": (5, "SideQuestionEntry"),
        "tokenfork": (6, "ForkSummaryEntry"),
        "tokennote": (7, "RewindEntry"),
        "tokenrationale": (7, "RewindEntry"),
        "tokencompaction": (8, "CompactionEntry"),
    }
    for token, (line_index, kind) in expected.items():
        matches = _search(app_env, session_id, token)["matches"]
        found = [(match["line_index"], match["kind"]) for match in matches]
        assert (line_index, kind) in found, f"{token!r} did not match line {line_index}"

    # The call id is searchable from the result side too, and the tool name
    # reaches both lines.
    assert [match["line_index"] for match in _search(app_env, session_id, "call-77")["matches"]] == [2, 3]
    assert [match["line_index"] for match in _search(app_env, session_id, "grep")["matches"]] == [2, 3]


def test_search_ignores_image_parts_but_keeps_the_text_beside_them(app_env: AppEnv) -> None:
    session_id = "find0004"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            message.UserMessage(
                parts=[
                    message.TextPart(text="look at this"),
                    message.ImageURLPart(url="data:image/png;base64,tokenbinary"),
                ]
            )
        ],
    )

    assert _search(app_env, session_id, "look")["total"] == 1
    assert _search(app_env, session_id, "tokenbinary")["total"] == 0


def test_search_still_finds_discarded_rows_and_reports_their_status(app_env: AppEnv) -> None:
    session_id = "find0005"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            _user("needle in the compacted prefix"),
            _user("needle that was retracted"),
            message.RetractEntry(retracted_text="needle that was retracted", retracted_line=1),
            message.CompactionEntry(summary="recap", first_kept_index=1, first_kept_line=4),
            _user("needle after the cut"),
        ],
    )

    matches = _search(app_env, session_id, "needle")["matches"]

    assert [(match["line_index"], match["status"]) for match in matches] == [
        (0, "compacted"),
        (1, "retracted"),
        # The retract entry quotes the withdrawn text, so it matches too.
        (2, "compacted"),
        (4, "active"),
    ]


def test_search_skips_lines_it_cannot_decode(app_env: AppEnv) -> None:
    session_id = "find0006"
    _write_session(
        app_env.work_dir,
        session_id,
        [
            _user("needle one"),
            '{"type": "NoSuchEntry", "data": {"text": "needle two"}}\n',
            "{not json at all needle three\n",
            _user("needle four"),
        ],
    )

    payload = _search(app_env, session_id, "needle")

    assert [match["line_index"] for match in payload["matches"]] == [0, 3]
    assert payload["total"] == 2
    assert "unknown" not in {match["status"] for match in payload["matches"]}


def test_search_limits_the_matches_but_counts_them_all(app_env: AppEnv) -> None:
    session_id = "find0007"
    _write_session(app_env.work_dir, session_id, [_user(f"needle {i}") for i in range(10)])

    payload = _search(app_env, session_id, "needle", limit=4)

    assert [match["line_index"] for match in payload["matches"]] == [0, 1, 2, 3]
    assert (payload["total"], payload["truncated"]) == (10, True)
    # The limit is clamped, never rejected, exactly like the history page.
    assert len(_search(app_env, session_id, "needle", limit=0)["matches"]) == 1
    everything = _search(app_env, session_id, "needle", limit=9999)
    assert len(everything["matches"]) == 10
    assert everything["truncated"] is False


def test_search_snippet_windows_around_the_first_hit(app_env: AppEnv) -> None:
    session_id = "find0008"
    filler = "x" * 400
    _write_session(app_env.work_dir, session_id, [_user(f"{filler} needle {filler}")])

    snippet = _search(app_env, session_id, "needle")["matches"][0]["snippet"]

    assert "needle" in snippet
    assert snippet.startswith("…") and snippet.endswith("…")
    assert len(snippet) <= 160
    # A short line needs no window at all.
    _write_session(app_env.work_dir, "find0009", [_user("just a needle")])
    assert _search(app_env, "find0009", "needle")["matches"][0]["snippet"] == "UserMessage just a needle"


def test_search_rejects_a_query_without_terms(app_env: AppEnv) -> None:
    session_id = "find0010"
    _write_session(app_env.work_dir, session_id, [_user("hi")])
    url = f"/api/web/sessions/{session_id}/search"

    assert app_env.client.get(url).status_code == 422
    assert app_env.client.get(url, params={"q": ""}).status_code == 422
    assert app_env.client.get(url, params={"q": "   "}).status_code == 422
    assert app_env.client.get(url, params={"q": "x" * 501}).status_code == 422
    assert app_env.client.get(url, params={"q": "x" * 500}).status_code == 200


def test_search_of_an_unknown_session_is_404(app_env: AppEnv) -> None:
    assert app_env.client.get("/api/web/sessions/nope/search", params={"q": "x"}).status_code == 404


# -- system context --


def _system_context(app_env: AppEnv, session_id: str) -> dict[str, Any]:
    response = app_env.client.get(f"/api/web/sessions/{session_id}/system-context")
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_system_context_rebuilds_for_a_cold_session(app_env: AppEnv) -> None:
    session_id = "sysctx01"
    _write_session(app_env.work_dir, session_id, [_user("hi")], meta_extra={"model_config_name": "sonnet"})

    payload = _system_context(app_env, session_id)

    assert payload["available"] is True
    assert payload["source"] == "rebuilt"
    assert isinstance(payload["system_prompt"], str) and payload["system_prompt"]
    assert payload["tools"], "the rebuilt profile must list the main agent tool set"
    assert {"name", "description", "parameters"} <= set(payload["tools"][0])
    assert "Bash" in {tool["name"] for tool in payload["tools"]}
    assert payload["model"]["model"] == "fake-model"
    assert payload["model"]["model_config_name"] == "sonnet"
    assert payload["reason"] is None
    # Reading a cold session must not spin up an agent for it.
    assert not app_env.runtime.session_registry.has_session_actor(session_id)


def test_system_context_reports_a_vanilla_session_without_the_main_prompt(app_env: AppEnv) -> None:
    session_id = "sysctx02"
    _write_session(app_env.work_dir, session_id, [], meta_extra={"vanilla": True})

    payload = _system_context(app_env, session_id)

    assert payload["source"] == "rebuilt"
    assert payload["system_prompt"] == "You're an agent running in user's terminal"
    assert {tool["name"] for tool in payload["tools"]} == {"Bash", "Edit", "Write", "Read"}


def test_system_context_serves_the_live_profile_for_a_loaded_session(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None

    payload = _system_context(app_env, session_id)

    assert payload["available"] is True
    assert payload["source"] == "live"
    # Exactly what the next step would put on the wire.
    assert payload["system_prompt"] == agent.profile.system_prompt
    assert [tool["name"] for tool in payload["tools"]] == [tool.name for tool in agent.profile.tools]
    assert payload["model"]["provider"] == "test"
    assert payload["model"]["model"] == "fake-model"


def test_system_context_never_leaks_a_credential(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    # The live path reads the client's config; plant a key in it.
    app_env.fake_llm.get_llm_config().api_key = "sk-LEAKED-SECRET"
    app_env.fake_llm.get_llm_config().aws_secret_key = "aws-LEAKED-SECRET"

    raw = app_env.client.get(f"/api/web/sessions/{session_id}/system-context").text

    assert "LEAKED" not in raw
    for banned in ("api_key", "aws_secret_key", "aws_access_key", "aws_session_token"):
        assert banned not in raw


def test_system_context_is_cached_per_session(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = "sysctx03"
    _write_session(app_env.work_dir, session_id, [])
    first = _system_context(app_env, session_id)

    def _boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("a cache hit must not rebuild")

    monkeypatch.setattr(web_api.system_context, "rebuilt_payload", _boom)

    assert _system_context(app_env, session_id) == first


def test_system_context_of_an_unknown_session_is_404(app_env: AppEnv) -> None:
    assert app_env.client.get("/api/web/sessions/nope/system-context").status_code == 404


# -- live session growth --


def test_history_follows_a_live_session_append(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="hi there"),
        message.AssistantMessage(parts=[message.TextPart(text="hi there")], stop_reason="stop"),
    )
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "hello"})
    assert response.status_code == 200

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()["state"] == "completed":
            break
        time.sleep(0.05)

    payload = _history(app_env, session_id)
    kinds = [row["entry"]["type"] for row in payload["rows"] if row["entry"] is not None]
    assert "UserMessage" in kinds
    assert "AssistantMessage" in kinds
    assert payload["line_count"] == len(payload["rows"])
    assert app_env.client.get(f"/api/web/sessions/{session_id}/meta").json()["line_count"] == payload["line_count"]
