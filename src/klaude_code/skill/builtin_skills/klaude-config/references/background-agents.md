---
name: background-agents
description: CLI commands for background agents and cross-session communication
---

# Background Agents & Cross-Session Communication

Each klaude process owns its conversation and child tasks. CLI control connects to the online process; `run` starts an independent background process and returns its session ID. Headless processes exit after their owned tasks and executable reports settle. Saved history remains readable after exit, but `send` cannot deliver to an offline session or restart it. Resume saved history explicitly with `klaude -r ID`.

Inside klaude, prefer native `Agent` and `ManageTasks` tools for owned work, and `ListPeers` / `MessagePeer` for peer coordination. The CLI is for external orchestration or fallback. Run `klaude --skill` for the current guide and agent types; `klaude models` lists models.

## Targets and status

A TARGET is a session ID, unique prefix, or `run --name` name. Ambiguous targets fail. Commands accepting multiple targets allow space- or comma-separated values; `--group` selects sessions tagged with `run --group NAME`.

```sh
klaude ps a3f2,fix-tests --json
klaude ps --group review --tree
klaude ps --history                 # include exited sessions
klaude brief fix-tests              # bounded status and pending request
```

`ps` defaults to online sessions; `--all` includes archived sessions, while `--history` includes exited history. Filters include `--dir`, repeatable `--state`, and `--limit`; `--watch` cannot be combined with `--json`. Sub-agents are hidden unless `--tree` is used.

States are `needs_you` (input, current error, or paused work), `working` (execution or admitted automatic work), and `idle` (no automatic work). Client connections do not determine state. JSON exposes execution, attention, continuation, and last-turn details separately. `brief` defaults to 4000 characters; `--full-last` preserves the last message.

## Start, wait, and read

```sh
id=$(klaude run -C ~/code/proj --name fix-tests "fix the failing tests")
klaude wait "$id" --timeout 600
klaude output "$id"                 # last assistant message
klaude output "$id" --turns 3       # last three turns
klaude output "$id" --transcript
klaude output "$id" --follow        # one target; live until turn ends
```

`run` supports `--agent`, `-m/--model`, `--group`, `--wait`, `--timeout` with `--wait`, and `--json`. Prompt text can come from an argument, piped stdin, or both; stdin is appended when data arrives within one second. `run --session ID` sends to an existing online session.

`wait` accepts targets, `--group`, or both. It waits until all selected sessions need attention or become idle; `--any` returns when the first settles. It is not a barrier over independent background Bash tasks. `--quiet` prints nothing. Exit codes: `0` idle, `2` needs input or is paused, `3` current error, `124` timeout, `1` usage or target error. A timeout does not stop work. With `--any`, output and status concern the settled sessions.

`output` and `wait` can read saved results after a process exits. `output --follow` requires one target and cannot be combined with `--group`, `--json`, `--turns`, or `--transcript`. Pending requests are shown with output. Multiple targets or a group produce labeled output blocks.

## Send and operator controls

```sh
klaude send fix-tests "please inspect the failing test"
klaude send fix-tests --message-id review-1 "check the auth flow"
klaude send fix-tests --reply-to review-1 "the relevant call is in server.py"
klaude brief fix-tests
klaude respond fix-tests --option 2  # operator answers a choice
klaude respond fix-tests --text "use staging"
klaude respond fix-tests --deny      # cancel the pending request
```

`send` delivers peer data to an online session at the next safe boundary. A receipt means accepted or queued, not read or answered. `--steer` is a compatibility alias for the default delivery; it does not interrupt the current stream or ordinary tools. `--from` is only a display label, not identity or operator authorization. Use a stable `--message-id` for idempotent retries (`task-result:` is reserved) and `--reply-to` for correlation. `--wait` waits for the session to settle and reads its latest output; it does not guarantee a reply to that message.

Peer messages do not answer pending interactions, grant permissions, or resume paused work. `respond` accepts exactly one of `--option`, `--text`, or `--deny`; there is no `--approve` option or `run --approval` policy. Inspect the request with `brief` and ask the operator to decide. Agents must not answer another peer's pending request or route a blocked action through a peer.

```sh
klaude interrupt fix-tests          # interrupt root inference/wait, like Esc
klaude interrupt --group review
klaude interrupt --all              # explicitly includes active child sessions
klaude unpause fix-tests            # operator allows pending work to continue
klaude dismiss fix-tests            # acknowledge error without resuming
klaude stop fix-tests               # stop this session's child agents
```

`interrupt` retains the session and pauses pending work; children and independent Bash tasks continue. Sending a message or restoring history does not clear the pause. `stop` affects child agents only, not the root, peers, or independent Bash tasks; `--children` is a compatibility alias. `unpause`, `dismiss`, and `respond` are operator controls.

## Background tasks

```sh
klaude tasks list "$id"
klaude tasks output "$id" TASK_ID --offset 0 --limit 16384
klaude tasks wait "$id" TASK_ID --timeout 600
klaude tasks stop "$id" TASK_ID
```

These commands inspect or control a session's owned Agent and Bash tasks. Follow `next_offset` for truncated output. A task wait timeout exits 124 without stopping the task. Reading output does not acknowledge model consumption. Recovery restores history and pending deliveries, not live execution stacks; unrecoverable active runs can become `lost`, so do not automatically replay side effects.

## Fan-out example

```sh
klaude run --group review --agent code-reviewer "review server/"
klaude run --group review --agent code-reviewer "review tui/"
klaude wait --group review --timeout 900
# Check the exit code and resolve attention or errors before synthesis.
klaude output --group review | klaude run --wait "merge and rank the findings"
```

Use `klaude wait --group review --any` to return when one session settles. For follow-up messages, check that the target remains online; an exited headless session must be resumed explicitly.
