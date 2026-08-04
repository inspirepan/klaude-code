"""Headless command surface: run / ps / brief / wait / output / send / respond / kill.

Thin client: every command is one or more HTTP calls over the server's Unix
socket. Heavy imports stay inside functions so each invocation starts fast.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from typing import Any

import typer

WAIT_POLL_INTERVAL_SECONDS = 1.0
PS_WATCH_INTERVAL_SECONDS = 1.0
FOLLOW_STATE_POLL_INTERVAL_SECONDS = 0.25
STDIN_POLL_SECONDS = 1.0

EXIT_USAGE = 1
EXIT_WAITING_INPUT = 2
EXIT_FAILED = 3
EXIT_TIMEOUT = 124

# Module-level singletons: B008 forbids these calls in argument defaults.
TARGETS_ARGUMENT = typer.Argument(None, metavar="[TARGET]...")
TEXT_ARGUMENT = typer.Argument(..., metavar="TEXT...")
STATE_OPTION = typer.Option(None, "--state", help="Filter by state (repeatable)")


# -- shared helpers --


def _api(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    from klaude_code.cli.uds_client import ServerNotRunningError, request_with_autostart

    try:
        status, body = request_with_autostart(method, path, json_body=json_body, params=params, timeout=timeout)
    except ServerNotRunningError as exc:
        typer.echo(f"error: klaude server is not reachable ({exc})", err=True)
        raise typer.Exit(EXIT_USAGE) from None
    if status >= 400:
        detail = body.get("detail") if isinstance(body, dict) else body
        if isinstance(detail, dict):
            message = detail.get("message", detail)
            typer.echo(f"error: {message}", err=True)
            candidates = detail.get("candidates")
            if isinstance(candidates, list) and candidates:
                typer.echo("candidates:", err=True)
                for candidate in candidates:
                    typer.echo(f"  {candidate}", err=True)
            agent_types = detail.get("agent_types")
            if isinstance(agent_types, list) and agent_types:
                typer.echo(f"agent types: {', '.join(agent_types)}", err=True)
        else:
            typer.echo(f"error: {detail}", err=True)
        raise typer.Exit(EXIT_USAGE)
    return body


def _split_targets(values: list[str]) -> list[str]:
    targets: list[str] = []
    for value in values:
        targets.extend(part.strip() for part in value.split(",") if part.strip())
    return targets


def _read_piped_stdin(*, has_prompt: bool) -> str:
    """Read piped stdin without hanging on an open-but-silent descriptor.

    Only FIFO/regular-file stdin counts as piped input. With an explicit
    PROMPT argument the read is skipped unless data shows up within
    STDIN_POLL_SECONDS — a caller-inherited pipe that never closes must not
    hang `run`. Without a PROMPT, block like any unix filter.
    """
    import os
    import select
    import stat

    if sys.stdin.isatty():
        return ""
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
    except (OSError, ValueError):
        return ""
    if not (stat.S_ISFIFO(mode) or stat.S_ISREG(mode)):
        return ""
    if has_prompt and stat.S_ISFIFO(mode):
        try:
            ready, _, _ = select.select([sys.stdin], [], [], STDIN_POLL_SECONDS)
        except (OSError, ValueError):
            return ""
        if not ready:
            return ""
    try:
        return sys.stdin.read().strip()
    except OSError:
        return ""


def _print_json(data: Any) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _short_id(session_id: str) -> str:
    return session_id[:8]


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _format_relative(timestamp: float) -> str:
    delta = max(0.0, time.time() - timestamp)
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _abbrev_home(path: str) -> str:
    from pathlib import Path

    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


def _fetch_rows(
    targets: list[str],
    group: str | None,
    *,
    states: list[str] | None = None,
    dir_: str | None = None,
    limit: int = 0,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    if targets:
        params["targets"] = ",".join(targets)
    if group:
        params["group"] = group
    if dir_:
        params["dir"] = dir_
    if states:
        params["state"] = states
    if include_archived:
        params["include_archived"] = True
    body = _api("GET", "/api/headless/sessions", params=params)
    sessions = body.get("sessions", [])
    return sessions if isinstance(sessions, list) else []


def _pending_request_lines(pending: dict[str, Any], *, target: str) -> list[str]:
    lines = [f"pending {pending.get('type', 'request')}: {pending.get('prompt', '')}"]
    options = pending.get("options") or []
    for option in options:
        description = option.get("description") or ""
        suffix = f" — {description}" if description else ""
        lines.append(f"  {option.get('index')}. {option.get('label')}{suffix}")
    if options:
        lines.append(f"answer with: klaude respond {target} --option N")
    else:
        lines.append(f"answer with: klaude respond {target} --text '...'")
    return lines


def _fetch_output(
    target: str,
    *,
    turns: int | None = None,
    transcript: bool = False,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if turns is not None:
        params["turns"] = turns
    if transcript:
        params["transcript"] = True
    return _api("GET", f"/api/headless/sessions/{target}/output", params=params)


_PS_COLUMNS = ("ID", "NAME", "TITLE", "STATE", "MODEL", "DIR", "ACTIVITY")


def _ps_table_rows(rows: list[dict[str, Any]]) -> list[tuple[str, ...]]:
    table_rows: list[tuple[str, ...]] = []
    for row in rows:
        state = str(row.get("state", ""))
        activity = row.get("activity")
        if not activity:
            updated_at = float(row.get("updated_at") or 0.0)
            prefix = "failed" if state == "failed" else "done"
            activity = f"{prefix} {_format_relative(updated_at)}" if updated_at else "-"
        table_rows.append(
            (
                _short_id(str(row.get("id", ""))),
                str(row.get("name") or "-"),
                _shorten(str(row.get("title") or "-"), 32),
                state,
                _shorten(str(row.get("model") or "-"), 20),
                _shorten(_abbrev_home(str(row.get("work_dir") or "-")), 28),
                _shorten(str(activity), 60),
            )
        )
    return table_rows


def _print_ps_table(rows: list[dict[str, Any]]) -> None:
    table = [_PS_COLUMNS, *_ps_table_rows(rows)]
    body_columns = len(_PS_COLUMNS) - 1
    widths = [max(len(line[column]) for line in table) for column in range(body_columns)]
    for line in table:
        cells = [line[column].ljust(widths[column]) for column in range(body_columns)]
        typer.echo("  ".join([*cells, line[body_columns]]).rstrip())


def _build_ps_rich_table(rows: list[dict[str, Any]]) -> Any:
    from rich import box
    from rich.table import Table

    table = Table(box=box.SIMPLE, expand=True)
    for column in _PS_COLUMNS:
        table.add_column(column, no_wrap=column != "ACTIVITY")
    for row in _ps_table_rows(rows):
        table.add_row(*row)
    if not rows:
        table.add_row(*["-"] * (len(_PS_COLUMNS) - 1), "no sessions")
    return table


def _watch_ps_rows(
    fetch: Callable[[], list[dict[str, Any]]],
    update: Callable[[list[dict[str, Any]]], None],
    *,
    interval: float = PS_WATCH_INTERVAL_SECONDS,
    max_refreshes: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Refresh rows until interrupted; max_refreshes makes tests finite."""
    refreshes = 0
    while max_refreshes is None or refreshes < max_refreshes:
        update(fetch())
        refreshes += 1
        if max_refreshes is not None and refreshes >= max_refreshes:
            return
        sleep(interval)


def _run_ps_watch(fetch: Callable[[], list[dict[str, Any]]]) -> None:
    from rich.console import Console
    from rich.live import Live

    console = Console()
    with Live(_build_ps_rich_table([]), console=console, refresh_per_second=4) as live:
        _watch_ps_rows(fetch, lambda rows: live.update(_build_ps_rich_table(rows), refresh=True))


def _write_follow_text(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


async def _follow_output_stream(
    session_id: str,
    *,
    initial_output: str,
) -> int:
    """Consume the server replay/live splice and print this turn's text once."""
    import asyncio
    import contextlib

    from websockets.asyncio.client import unix_connect

    from klaude_code.protocol import events
    from klaude_code.server.paths import server_socket_path

    uri = f"ws://klaude/api/sessions/{session_id}/ws?replay=1&peek=1"
    streamed_parts: list[str] = []
    seen_sequences: set[int] = set()
    terminal_state: str | None = None
    disconnected = False
    websocket: Any = None

    try:
        websocket = await unix_connect(
            path=str(server_socket_path()),
            uri=uri,
            max_size=64 * 1024 * 1024,
            ping_interval=None,
        )
    except Exception as exc:
        typer.echo(f"error: cannot connect to klaude server WebSocket ({exc})", err=True)
        return EXIT_FAILED

    try:
        while terminal_state is None:
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=FOLLOW_STATE_POLL_INTERVAL_SECONDS)
            except TimeoutError:
                raw = None
            except Exception:
                disconnected = True
                break

            if raw is not None:
                try:
                    frame = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    frame = None
                items = frame if isinstance(frame, list) else [frame]
                for item in items:
                    if not isinstance(item, dict) or item.get("session_id") not in (None, session_id):
                        continue
                    # Handshake and replay control frames are not event
                    # envelopes. They do not carry output.
                    if isinstance(item.get("type"), str):
                        continue
                    try:
                        envelope = events.parse_event_envelope(item)
                    except ValueError:
                        continue
                    sequence = envelope.event_seq
                    if sequence > 0 and sequence in seen_sequences:
                        continue
                    if sequence > 0:
                        seen_sequences.add(sequence)
                    event = envelope.event
                    if isinstance(event, events.AssistantTextDeltaEvent):
                        content = event.content
                        streamed_parts.append(content)
                        _write_follow_text(content)
                    elif isinstance(event, events.ErrorEvent):
                        terminal_state = "failed"
                        typer.echo(
                            f"error: {event.compact_message or event.error_message or 'agent failed'}",
                            err=True,
                        )
                    elif isinstance(event, events.UserInteractionRequestEvent):
                        terminal_state = "waiting_input"

            if terminal_state is not None:
                break
            rows = await asyncio.to_thread(_fetch_rows, [session_id], None)
            if not rows:
                typer.echo("error: session disappeared while following output", err=True)
                return EXIT_USAGE
            row = rows[0]
            state = str(row.get("state") or "idle")
            if state in ("waiting_input", "failed") or (
                state not in ("queued", "running") and not bool(row.get("pending"))
            ):
                terminal_state = state
    finally:
        if websocket is not None:
            with contextlib.suppress(Exception):
                await websocket.close()

    result = await asyncio.to_thread(_fetch_output, session_id)
    final_output = str(result.get("output") or "")
    streamed = "".join(streamed_parts)
    if final_output != initial_output and final_output.startswith(streamed):
        _write_follow_text(final_output[len(streamed) :])
        streamed = final_output
    if streamed and not streamed.endswith("\n"):
        _write_follow_text("\n")

    pending = result.get("pending_request")
    if isinstance(pending, dict):
        for line in _pending_request_lines(pending, target=_short_id(session_id)):
            typer.echo(line)

    final_state = str(result.get("state") or "idle")
    if (
        disconnected
        and terminal_state is None
        and (final_state in ("queued", "running") or bool(result.get("pending")))
    ):
        typer.echo("error: connection to klaude server lost while session was active", err=True)
        return EXIT_FAILED
    return _exit_code_for_states([terminal_state or final_state])


def _print_output_block(result: dict[str, Any], *, with_header: bool) -> None:
    if with_header:
        name = result.get("name") or "-"
        typer.echo(f"== {_short_id(str(result.get('id', '')))} {name}")
    output = str(result.get("output") or "")
    if output:
        typer.echo(output)
    pending = result.get("pending_request")
    if isinstance(pending, dict):
        target = str(result.get("id", ""))[:8]
        for line in _pending_request_lines(pending, target=target):
            typer.echo(line)


def _poll_until_settled(
    targets: list[str],
    group: str | None,
    *,
    timeout: float | None,
    any_mode: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """Poll until targets leave queued/running. Returns (rows, timed_out)."""
    deadline = time.monotonic() + timeout if timeout is not None else None
    while True:
        rows = _fetch_rows(targets, group)
        if not rows:
            typer.echo("error: no matching sessions", err=True)
            raise typer.Exit(EXIT_USAGE)
        settled = [
            row
            for row in rows
            if row.get("state") == "waiting_input"
            or (row.get("state") not in ("queued", "running") and not bool(row.get("pending")))
        ]
        if any_mode and settled:
            return rows, False
        if len(settled) == len(rows):
            return rows, False
        if deadline is not None and time.monotonic() >= deadline:
            return rows, True
        time.sleep(WAIT_POLL_INTERVAL_SECONDS)


def _exit_code_for_states(states: list[str]) -> int:
    if any(state == "failed" for state in states):
        return EXIT_FAILED
    if any(state == "waiting_input" for state in states):
        return EXIT_WAITING_INPUT
    return 0


# -- run --


def run_command(
    prompt: str | None = typer.Argument(None, metavar="[PROMPT]"),
    dir_: str | None = typer.Option(None, "--dir", "-C", help="Working directory (default: cwd)"),
    model: str | None = typer.Option(
        None, "--model", "-m", help="Model alias (see `klaude agents`); defaults to the agent type's bound model"
    ),
    agent: str = typer.Option(
        "main",
        "--agent",
        show_default=False,
        help="Agent type (see `klaude agents`). Default: main — the full agent with all tools. "
        "Other types (finder, code-reviewer, ...) run with their own prompt, tool set, and bound model",
    ),
    name: str | None = typer.Option(None, "--name", help="Addressable name for ps/brief/wait/send"),
    group: str | None = typer.Option(
        None,
        "--group",
        help="Tag this session for `ps --group NAME`. Lets a calling agent find everything it "
        "spawned even after it lost the ids",
    ),
    session: str | None = typer.Option(
        None, "--session", help="Send into an existing session instead of creating a new one (same as `klaude send`)"
    ),
    approval: str = typer.Option(
        "hold",
        "--approval",
        show_default=False,
        help="What to do on permission requests when no human is attached: "
        "hold = park request, state=waiting_input (default); "
        "auto = approve permission requests (questions still park as waiting_input); use only in trusted dirs; "
        "deny = reject; agent must work around",
    ),
    wait: bool = typer.Option(False, "--wait", help="Block until finished, print final output"),
    timeout: float | None = typer.Option(None, "--timeout", metavar="SECS", help="With --wait: exit 124 on timeout"),
    json_: bool = typer.Option(False, "--json", help='Print {"session_id": ..., "name": ...}'),
) -> None:
    """Spawn a background agent on the server and print its session id, then return immediately.

    The agent keeps running after this command exits. PROMPT is read from the
    argument, or from stdin when piped. When both are given, stdin is appended
    to PROMPT — but only if pipe data arrives within 1s, so an inherited
    pipe that never closes cannot hang the command.

    \b
    Examples:
      klaude run "fix the failing tests under tests/server/"
      klaude run -C ~/code/proj -m sonnet --name fix-tests "..."
      git diff | klaude run --agent code-reviewer "review this diff"
      klaude run --wait "one-shot question, print answer when done"
    """
    from pathlib import Path

    prompt_text = (prompt or "").strip()
    stdin_text = _read_piped_stdin(has_prompt=bool(prompt_text))
    if stdin_text:
        prompt_text = f"{prompt_text}\n\n{stdin_text}" if prompt_text else stdin_text
    if not prompt_text:
        typer.echo("error: no prompt given (pass PROMPT or pipe stdin)", err=True)
        raise typer.Exit(EXIT_USAGE)
    if approval not in ("hold", "auto", "deny"):
        typer.echo("error: --approval must be one of: hold, auto, deny", err=True)
        raise typer.Exit(EXIT_USAGE)

    if session is not None:
        _send_message(session, prompt_text, wait=wait, timeout=timeout, json_=json_)
        return

    work_dir = str(Path(dir_).expanduser().resolve()) if dir_ else str(Path.cwd())
    body = _api(
        "POST",
        "/api/headless/run",
        json_body={
            "prompt": prompt_text,
            "work_dir": work_dir,
            "model": model,
            "agent": agent,
            "name": name,
            "group": group,
            "approval": approval,
        },
    )
    session_id = str(body.get("session_id", ""))
    run_state = str(body.get("state", ""))

    if not wait:
        if json_:
            _print_json({"session_id": session_id, "name": body.get("name"), "state": run_state})
        else:
            typer.echo(session_id)
            if run_state == "queued":
                typer.echo("queued: waiting for a free slot (see `klaude ps`)", err=True)
        return

    rows, timed_out = _poll_until_settled([session_id], None, timeout=timeout)
    if timed_out:
        typer.echo(f"timeout: {_short_id(session_id)} is still {rows[0].get('state')}", err=True)
        raise typer.Exit(EXIT_TIMEOUT)
    result = _fetch_output(session_id)
    if json_:
        _print_json({"session_id": session_id, "name": body.get("name"), "state": rows[0].get("state"), **result})
    else:
        _print_output_block(result, with_header=False)
    raise typer.Exit(_exit_code_for_states([str(row.get("state")) for row in rows]))


# -- ps --


def ps_command(
    targets: list[str] | None = TARGETS_ARGUMENT,
    group: str | None = typer.Option(None, "--group", help="Only sessions spawned with `run --group NAME`"),
    dir_: str | None = typer.Option(None, "--dir", help="Only sessions under PATH"),
    states: list[str] | None = STATE_OPTION,
    limit: int = typer.Option(20, "--limit", "-n", show_default=False, help="Max rows (default 20)"),
    show_all: bool = typer.Option(False, "--all", help="Include archived sessions"),
    watch: bool = typer.Option(False, "--watch", help="Live-refreshing table (human view)"),
    json_: bool = typer.Option(False, "--json", help="Machine-readable"),
) -> None:
    """List sessions known to the server.

    Active sessions (queued, running, waiting_input) always sort first, then by
    most recently updated. With TARGETs — ids, unique prefixes, or names;
    space- or comma-separated — show only those sessions. This is the usual
    form for a calling agent: check exactly the agents it spawned, nothing else.

    \b
      klaude ps a3f2c1,9b01d4,fix-tests --json

    ACTIVITY is the current tool call when running, the pending request when
    waiting_input, and relative finish time when idle/failed.

    --watch refreshes the human table until Ctrl-C and cannot be combined with
    --json.
    """
    if watch and json_:
        raise typer.BadParameter("--watch and --json are mutually exclusive")

    target_list = _split_targets(targets or [])

    def fetch() -> list[dict[str, Any]]:
        return _fetch_rows(
            target_list,
            group,
            states=states,
            dir_=dir_,
            limit=0 if show_all else limit,
            include_archived=show_all,
        )

    if watch:
        try:
            _run_ps_watch(fetch)
        except KeyboardInterrupt:
            return
        return

    rows = fetch()
    if json_:
        _print_json({"sessions": rows})
        return
    if not rows:
        typer.echo("no sessions")
        return

    _print_ps_table(rows)


# -- brief --


def brief_command(
    target: str = typer.Argument(..., metavar="TARGET"),
    max_chars: int = typer.Option(2000, "--max-chars", show_default=False, help="Output budget (default 2000)"),
    full_last: bool = typer.Option(False, "--full-last", help="Do not truncate the last assistant message"),
    json_: bool = typer.Option(False, "--json", help="Machine-readable"),
) -> None:
    """Print a compact, bounded summary of one session — sized to fit in a calling agent's context.

    Never dumps the full transcript.

    \b
    Sections: state, title, model, dir, todos, current/last tool call,
    pending request (when waiting_input), last assistant message
    (truncated), token usage, changed-files summary.
    """
    body = _api("GET", f"/api/headless/sessions/{target}/brief")
    if json_:
        _print_json(body)
        return

    lines: list[str] = []
    name = body.get("name")
    header = f"{_short_id(str(body.get('id', '')))}"
    if name:
        header += f" ({name})"
    lines.append(f"session: {header}")
    lines.append(f"state: {body.get('state')}")
    if body.get("title"):
        lines.append(f"title: {body.get('title')}")
    lines.append(f"model: {body.get('model') or '-'}")
    lines.append(f"dir: {_abbrev_home(str(body.get('work_dir') or '-'))}")
    if body.get("agent_type"):
        lines.append(f"agent: {body.get('agent_type')}")
    if body.get("approval_policy"):
        lines.append(f"approval: {body.get('approval_policy')}")

    todos = body.get("todos") or []
    if todos:
        lines.append("todos:")
        for todo in todos:
            marker = "x" if todo.get("status") == "completed" else ">" if todo.get("status") == "in_progress" else " "
            lines.append(f"  [{marker}] {todo.get('content')}")

    if body.get("current_tool_call"):
        lines.append(f"current tool: {body.get('current_tool_call')}")

    pending = body.get("pending_request")
    if isinstance(pending, dict):
        lines.extend(_pending_request_lines(pending, target=target))

    usage = body.get("usage")
    if isinstance(usage, dict):
        context_size = usage.get("context_size")
        context_limit = usage.get("context_limit")
        context = f", context {context_size}/{context_limit}" if context_size and context_limit else ""
        lines.append(
            f"tokens: in {usage.get('input_tokens')}, out {usage.get('output_tokens')}, "
            f"cached {usage.get('cached_tokens')}{context}"
        )

    changes = body.get("file_change_summary") or {}
    edited = list(changes.get("edited_files") or []) + list(changes.get("created_files") or [])
    if edited or changes.get("diff_lines_added") or changes.get("diff_lines_removed"):
        lines.append(
            f"files: +{changes.get('diff_lines_added', 0)}/-{changes.get('diff_lines_removed', 0)} "
            f"({', '.join(edited[:8])})"
        )

    last_message = str(body.get("last_assistant_message") or "")
    if last_message:
        used = sum(len(line) + 1 for line in lines) + len("last message:\n")
        budget = max(200, max_chars - used)
        if not full_last and len(last_message) > budget:
            last_message = last_message[:budget] + "… [truncated, use `klaude output` for full text]"
        lines.append("last message:")
        lines.append(last_message)

    typer.echo("\n".join(lines))


# -- wait --


def wait_command(
    targets: list[str] | None = TARGETS_ARGUMENT,
    group: str | None = typer.Option(None, "--group", help="Wait for every session spawned with this group"),
    timeout: float | None = typer.Option(None, "--timeout", metavar="SECS", help="Give up after SECS (exit 124)"),
    any_: bool = typer.Option(False, "--any", help="Return when the first target finishes"),
    quiet: bool = typer.Option(False, "--quiet", help="Exit code only, print nothing"),
    json_: bool = typer.Option(False, "--json", help="Machine-readable"),
) -> None:
    """Block until the given agents leave the queued/running states, then print each one's final output.

    When a session stopped at waiting_input, its pending question is printed
    instead. Give TARGETs, --group, or both.

    \b
    Exit codes: 0 all idle · 2 some waiting_input · 3 some failed · 124 timeout.

    \b
    Examples:
      klaude wait a3f2,9b01                    # barrier over two agents
      klaude wait --group review --timeout 900 # barrier over a fan-out
      klaude wait --group review --any         # first finisher wins
    """
    target_list = _split_targets(targets or [])
    if not target_list and not group:
        typer.echo("error: give TARGETs, --group, or both", err=True)
        raise typer.Exit(EXIT_USAGE)

    rows, timed_out = _poll_until_settled(target_list, group, timeout=timeout, any_mode=any_)
    if timed_out:
        if not quiet:
            still = [row for row in rows if row.get("state") in ("queued", "running")]
            for row in still:
                typer.echo(f"timeout: {_short_id(str(row.get('id', '')))} is still {row.get('state')}", err=True)
        raise typer.Exit(EXIT_TIMEOUT)

    settled = [row for row in rows if row.get("state") not in ("queued", "running")]
    exit_code = _exit_code_for_states([str(row.get("state")) for row in settled])

    if quiet:
        raise typer.Exit(exit_code)

    results: list[dict[str, Any]] = []
    for row in settled:
        result = _fetch_output(str(row.get("id")))
        result["state"] = row.get("state")
        results.append(result)
    if json_:
        _print_json({"sessions": results})
    else:
        for result in results:
            _print_output_block(result, with_header=len(results) > 1)
    raise typer.Exit(exit_code)


# -- output --


def output_command(
    targets: list[str] | None = TARGETS_ARGUMENT,
    group: str | None = typer.Option(None, "--group", help="All sessions spawned with this group"),
    turns: int | None = typer.Option(None, "--turns", metavar="N", help="Last N user+assistant turns"),
    transcript: bool = typer.Option(False, "--transcript", help="Full transcript rendered as plain text"),
    follow: bool = typer.Option(False, "--follow", help="Stream live output until idle (single target)"),
    json_: bool = typer.Option(False, "--json", help="Machine-readable"),
) -> None:
    """Print sessions' output. Default: the last assistant message only.

    With multiple TARGETs or --group, each output is printed under a
    `== <id> <name>` header — pipe the lot into a synthesis agent:

    \b
      klaude output --group review | klaude run --wait "dedupe and rank"

    When a session is waiting_input, its pending request (type, prompt,
    options) is appended after the output.

    --follow accepts exactly one TARGET. It cannot be combined with --group,
    --json, --turns, or --transcript.
    """
    target_list = _split_targets(targets or [])
    if follow:
        if json_:
            raise typer.BadParameter("--follow and --json are mutually exclusive")
        if group or len(target_list) != 1:
            raise typer.BadParameter("--follow requires exactly one TARGET and cannot be used with --group")
        if turns is not None or transcript:
            raise typer.BadParameter("--follow cannot be used with --turns or --transcript")

    if not target_list and not group:
        typer.echo("error: give TARGETs, --group, or both", err=True)
        raise typer.Exit(EXIT_USAGE)

    if follow:
        import asyncio

        initial = _fetch_output(target_list[0])
        state = str(initial.get("state") or "idle")
        if state in ("waiting_input", "failed"):
            pending = initial.get("pending_request")
            if isinstance(pending, dict):
                for line in _pending_request_lines(pending, target=_short_id(str(initial.get("id") or ""))):
                    typer.echo(line)
            raise typer.Exit(_exit_code_for_states([state]))
        if state not in ("queued", "running") and not bool(initial.get("pending")):
            return
        session_id = str(initial.get("id") or "")
        initial_output = str(initial.get("output") or "")
        try:
            exit_code = asyncio.run(_follow_output_stream(session_id, initial_output=initial_output))
        except KeyboardInterrupt:
            return
        if exit_code:
            raise typer.Exit(exit_code)
        return

    ids: list[str]
    if target_list and not group:
        ids = target_list
    else:
        rows = _fetch_rows(target_list, group)
        ids = [str(row.get("id")) for row in rows]
    if not ids:
        typer.echo("error: no matching sessions", err=True)
        raise typer.Exit(EXIT_USAGE)

    results = [_fetch_output(target, turns=turns, transcript=transcript) for target in ids]
    if json_:
        _print_json({"sessions": results})
        return
    for result in results:
        _print_output_block(result, with_header=len(results) > 1)


# -- send --


def _send_message(
    target: str, text: str, *, wait: bool, timeout: float | None, json_: bool, steer: bool = False
) -> None:
    body = _api("POST", f"/api/headless/sessions/{target}/send", json_body={"text": text, "steer": steer})
    session_id = str(body.get("session_id", ""))
    mode = str(body.get("mode", ""))

    if not wait:
        if json_:
            _print_json({"session_id": session_id, "mode": mode})
        elif mode == "queued":
            typer.echo(f"queued for {_short_id(session_id)}: delivered when the current turn finishes")
        else:
            typer.echo(f"started turn on {_short_id(session_id)}")
        return

    rows, timed_out = _poll_until_settled([session_id], None, timeout=timeout)
    if timed_out:
        typer.echo(f"timeout: {_short_id(session_id)} is still {rows[0].get('state')}", err=True)
        raise typer.Exit(EXIT_TIMEOUT)
    result = _fetch_output(session_id)
    if json_:
        _print_json({"session_id": session_id, "mode": mode, "state": rows[0].get("state"), **result})
    else:
        _print_output_block(result, with_header=False)
    raise typer.Exit(_exit_code_for_states([str(row.get("state")) for row in rows]))


def send_command(
    target: str = typer.Argument(..., metavar="TARGET"),
    text: list[str] = TEXT_ARGUMENT,
    steer: bool = typer.Option(False, "--steer", help="Deliver immediately, interrupting work"),
    wait: bool = typer.Option(False, "--wait", help="Block until the resulting turn finishes"),
    timeout: float | None = typer.Option(None, "--timeout", metavar="SECS", help="With --wait"),
    json_: bool = typer.Option(False, "--json", help="Machine-readable"),
) -> None:
    """Send a message to a session.

    \b
      idle session:     starts a new turn immediately — the follow-up
                        keeps the full conversation context
      running session:  queued by default; delivered when the current
                        turn finishes (like typing while klaude works)
      --steer:          interrupt the running turn and inject the
                        message now (course-correction)

    Sessions never expire: send works minutes or days after the last turn,
    and across server restarts — the conversation is reloaded from disk on
    demand. This is how a calling agent iterates with the same klaude agent
    over many rounds:

    \b
      id=$(klaude run "read the codebase, summarize the auth flow")
      klaude wait "$id"
      klaude send "$id" --wait "now write tests for the edge cases you found"
      klaude send "$id" --wait "one of them fails, here is the log: ..."

    Note: send does NOT answer a pending interaction — a session parked
    at waiting_input needs `klaude respond`.
    """
    message = " ".join(text).strip()
    if not message:
        typer.echo("error: message text is empty", err=True)
        raise typer.Exit(EXIT_USAGE)
    _send_message(target, message, wait=wait, timeout=timeout, json_=json_, steer=steer)


# -- respond --


def respond_command(
    target: str = typer.Argument(..., metavar="TARGET"),
    approve: bool = typer.Option(False, "--approve", help="For permission requests"),
    deny: bool = typer.Option(False, "--deny", help="For permission requests; cancels other request kinds"),
    option: int | None = typer.Option(None, "--option", metavar="N", help="Pick option N of a choice request"),
    text: str | None = typer.Option(None, "--text", help="Free-text answer"),
    json_: bool = typer.Option(False, "--json", help="Machine-readable"),
) -> None:
    """Answer a session's pending interaction (approval, choice, or text).

    Run `klaude brief TARGET` first to see the request and its options.
    """
    actions: list[tuple[str, dict[str, Any]]] = []
    if approve:
        actions.append(("approve", {}))
    if deny:
        actions.append(("deny", {}))
    if option is not None:
        actions.append(("option", {"option": option}))
    if text is not None:
        actions.append(("text", {"text": text}))
    if len(actions) != 1:
        typer.echo("error: pass exactly one of --approve / --deny / --option N / --text TEXT", err=True)
        raise typer.Exit(EXIT_USAGE)

    action, extra = actions[0]
    body = _api(
        "POST",
        f"/api/headless/sessions/{target}/respond",
        json_body={"action": action, **extra},
    )
    if json_:
        _print_json(body)
    else:
        typer.echo(f"answered {body.get('request_id')} ({body.get('status')})")


# -- kill --


def kill_command(
    targets: list[str] | None = TARGETS_ARGUMENT,
    group: str | None = typer.Option(None, "--group", help="Interrupt every session in this group"),
    all_: bool = typer.Option(False, "--all", help="Interrupt every running session"),
) -> None:
    """Interrupt a running agent — same as pressing Esc in the TUI.

    The session is kept and stays resumable via `send` or `attach`.
    """
    target_list = _split_targets(targets or [])
    if not target_list and not group and not all_:
        typer.echo("error: give TARGETs, --group, or --all", err=True)
        raise typer.Exit(EXIT_USAGE)

    ids: list[str]
    if all_ or group:
        rows = _fetch_rows(target_list, group, states=["queued", "running", "waiting_input"])
        ids = [str(row.get("id")) for row in rows]
    else:
        ids = target_list
    if not ids:
        typer.echo("nothing to interrupt")
        return

    for target in ids:
        body = _api("POST", f"/api/headless/sessions/{target}/interrupt")
        typer.echo(f"interrupted {_short_id(str(body.get('session_id', target)))} (was {body.get('was')})")


def register_headless_commands(app: typer.Typer) -> None:
    app.command("run")(run_command)
    app.command("ps")(ps_command)
    app.command("brief")(brief_command)
    app.command("wait")(wait_command)
    app.command("output")(output_command)
    app.command("send")(send_command)
    app.command("respond")(respond_command)
    app.command("kill")(kill_command)
