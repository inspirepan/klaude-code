"""`klaude agents`: discovery command for agent types and model aliases.

Three views over the same inventory: rich (humans), --json (programs),
--prime (a generated Markdown integration guide for AI agents).
"""

from __future__ import annotations

import json
import sys
from typing import Any

import typer

EXIT_CODES_TABLE = [
    ("0", "success (`wait`: all sessions completed)"),
    ("1", "usage error / target not found / ambiguous target"),
    ("2", "`wait`: some session stopped at waiting_input"),
    ("3", "`wait`: some session failed"),
    ("124", "--timeout expired (same convention as timeout(1))"),
]


def _load_config_or_exit() -> Any:
    from klaude_code.config import ConfigValidationError, load_config

    try:
        return load_config()
    except ConfigValidationError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None


def build_agent_inventory(config: Any) -> list[dict[str, Any]]:
    from klaude_code.config.config import format_model_preference
    from klaude_code.config.sub_agent_model import SubAgentModelResolver

    main_model = format_model_preference(config.main_model) or "(not configured)"
    rows: list[dict[str, Any]] = [
        {
            "name": "main",
            "summary": "The full coding agent: all tools, full system prompt. Default for `klaude run`.",
            "tools": "all main-agent tools",
            "model": main_model,
        }
    ]
    resolver = SubAgentModelResolver(config)
    for info in resolver.get_available_sub_agents():
        profile = info.profile
        model = format_model_preference(info.effective_model) or main_model
        tools = ", ".join(profile.tool_set) if profile.tool_set else "main-agent tool set"
        rows.append(
            {
                "name": profile.name,
                "summary": " ".join(profile.invoker_summary.split()),
                "tools": tools,
                "model": model,
            }
        )
    return rows


def build_model_inventory(config: Any) -> list[dict[str, Any]]:
    return [
        {
            "selector": entry.selector,
            "model_name": entry.model_name,
            "provider": entry.provider,
            "model_id": entry.model_id,
        }
        for entry in config.iter_model_entries(only_available=True, include_disabled=False)
    ]


def build_json_inventory(config: Any) -> dict[str, Any]:
    from klaude_code.config.config import format_model_preference

    return {
        "agent_types": build_agent_inventory(config),
        "models": build_model_inventory(config),
        "defaults": {
            "main_model": format_model_preference(config.main_model),
            "fast_model": format_model_preference(config.fast_model),
            "compact_model": format_model_preference(config.compact_model),
            "headless_max_running": config.headless_max_running,
        },
    }


def build_prime_guide(config: Any) -> str:
    agents = build_agent_inventory(config)
    models = build_model_inventory(config)

    lines: list[str] = []
    lines.append("# Driving klaude from another agent")
    lines.append("")
    lines.append(
        "klaude is an agent multiplexer: a single local server owns all execution, "
        "and every CLI command below is a thin client of it. `run` returns immediately, "
        "multi-target `wait` is a barrier, `--group` names a fan-out. Orchestration is plain bash."
    )
    lines.append("")
    lines.append("## Command cheatsheet")
    lines.append("")
    lines.append("```bash")
    lines.append('id=$(klaude run --group me "task...")     # spawn, returns session id at once')
    lines.append("klaude ps $id                              # state + current activity")
    lines.append("klaude brief $id                           # compact bounded status report")
    lines.append("klaude wait $id --timeout 600              # block until it settles")
    lines.append("klaude output $id                          # last assistant message")
    lines.append('klaude send $id --wait "follow-up..."      # next turn, same context')
    lines.append("klaude respond $id --option 2              # answer a pending question")
    lines.append("klaude kill $id                            # interrupt; session stays resumable")
    lines.append("```")
    lines.append("")
    lines.append("## The standard closed loop")
    lines.append("")
    lines.append("```bash")
    lines.append('id=$(klaude run --group me "task...")')
    lines.append('klaude wait "$id" --timeout 600')
    lines.append("case $? in")
    lines.append('  0) klaude output "$id" ;;             # done, take the result')
    lines.append('  2) klaude brief "$id"                 # see what it is asking')
    lines.append('     klaude respond "$id" --approve     # or --deny / --option N / --text')
    lines.append('     klaude wait "$id" ;;               # keep waiting')
    lines.append('  3) klaude output "$id" ;;             # inspect the failure, send retry or kill')
    lines.append('  124) klaude brief "$id" ;;            # still running at timeout')
    lines.append("esac")
    lines.append("```")
    lines.append("")
    lines.append("## Orchestration patterns")
    lines.append("")
    lines.append("- Parallel fan-out + barrier:")
    lines.append("")
    lines.append("```bash")
    lines.append('G="review-$(git rev-parse --short HEAD)"')
    lines.append("git diff --name-only main | \\")
    lines.append('  xargs -I{} klaude run --group "$G" --agent code-reviewer "review the changes in {}"')
    lines.append('klaude wait --group "$G" --timeout 900')
    lines.append("```")
    lines.append("")
    lines.append("- Synthesis pipeline (pipe N reports into one summarizer):")
    lines.append("")
    lines.append("```bash")
    lines.append('klaude output --group "$G" | klaude run --wait "dedupe these findings, rank by severity"')
    lines.append("```")
    lines.append("")
    lines.append('- Race (first finisher wins): `klaude wait --group "$G" --any`')
    lines.append("- Loop until done: bash `while` + `klaude run --wait` + exit codes.")
    lines.append(
        '- Multi-round iteration: `klaude send ID --wait "..."` keeps the full conversation '
        "context across turns, days, and server restarts."
    )
    lines.append(
        "- The server caps concurrently running headless agents "
        f"(currently {config.headless_max_running}); extra runs queue as `queued` and `wait` keeps blocking."
    )
    lines.append(
        "- `run --approval auto` approves every permission request without checking the directory; "
        "use it only in trusted directories."
    )
    lines.append("")
    lines.append("## TARGET rules")
    lines.append("")
    lines.append(
        "TARGET = session id (a unique prefix is enough) or the `--name` given at `klaude run`. "
        "Commands taking multiple TARGETs accept space- or comma-separated lists. "
        "Names must be unique among active sessions. Ambiguous targets fail with the candidate list."
    )
    lines.append("")
    lines.append("## Exit codes")
    lines.append("")
    lines.append("| code | meaning |")
    lines.append("|---|---|")
    for code, meaning in EXIT_CODES_TABLE:
        lines.append(f"| {code} | {meaning} |")
    lines.append("")
    lines.append("## Agent types (`klaude run --agent TYPE`)")
    lines.append("")
    for agent in agents:
        lines.append(f"- `{agent['name']}` — {agent['summary']} (tools: {agent['tools']}; model: {agent['model']})")
    lines.append("")
    lines.append("## Model aliases (`klaude run -m ALIAS`)")
    lines.append("")
    for model in models:
        lines.append(f"- `{model['selector']}` → {model['model_id']}")
    lines.append("")
    lines.append(
        "States: queued (waiting for a server slot) · running · waiting_input "
        "(parked on a question/approval — answer with `klaude respond`) · completed "
        "(turn finished; `send` continues it) · idle (a TUI is attached, waiting at "
        "the prompt) · failed (last turn errored; `send` retries)."
    )
    return "\n".join(lines)


def agents_command(
    json_: bool = typer.Option(False, "--json", help="Machine-readable inventory: agent types, models, defaults"),
    prime: bool = typer.Option(
        False,
        "--prime",
        help="Markdown integration guide for AI agents that drive klaude through a shell tool. "
        "Paste into CLAUDE.md / AGENTS.md, or have the agent run `klaude agents --prime` once before using klaude",
    ),
) -> None:
    """Show what this klaude can run.

    \b
      agent types  values for `klaude run --agent`, with purpose, tool
                   access, and bound model
      models       configured model aliases grouped by provider, with
                   upstream id and thinking/effort variants

    The default output is a rich view for humans. Use --json or --prime
    when the reader is a program or an AI agent.
    """
    config = _load_config_or_exit()

    if json_:
        typer.echo(json.dumps(build_json_inventory(config), ensure_ascii=False, indent=2))
        return
    if prime:
        typer.echo(build_prime_guide(config))
        return

    _render_rich_view(config)


def _render_rich_view(config: Any) -> None:
    from rich.console import Console
    from rich.text import Text

    from klaude_code.cli.list_model import display_models_and_providers
    from klaude_code.tui.components.rich.theme import get_theme
    from klaude_code.tui.terminal.color import is_light_terminal_background

    if config.theme is None and sys.stdout.isatty():
        detected = is_light_terminal_background()
        if detected is True:
            config.theme = "light"
        elif detected is False:
            config.theme = "dark"

    console = Console(theme=get_theme(config.theme).app_theme)
    console.print(Text("Agent types (klaude run --agent TYPE)", style="bold"))
    for agent in build_agent_inventory(config):
        summary = agent["summary"]
        if len(summary) > 240:
            summary = summary[:239] + "…"
        header = Text()
        header.append(f"  {agent['name']}", style="bold cyan")
        header.append("  ·  ", style="dim")
        header.append(str(agent["model"]))
        console.print(header)
        console.print(Text(f"    tools: {agent['tools']}", style="dim"))
        if summary:
            console.print(Text(f"    {summary}", style="dim"))
    console.print()
    display_models_and_providers(config, show_all=False)


def register_agents_command(app: typer.Typer) -> None:
    app.command("agents")(agents_command)
