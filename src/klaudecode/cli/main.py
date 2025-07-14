import asyncio
import shutil
import sys
from pathlib import Path
from typing import Optional

import typer

from ..agent import get_main_agent
from ..message import SystemMessage
from ..prompt.system import STATIC_SYSTEM_PROMPT, get_system_prompt_dynamic_part
from ..session import Session
from ..tui import ColorStyle, Text, console, render_hello, render_logo, render_tips
from ..user_input import user_select
from ..utils.exception import format_exception
from ..utils.str_utils import format_relative_time
from .config import setup_config


async def get_session(ctx: typer.Context) -> Optional[Session]:
    if ctx.obj['continue_latest']:
        session = Session.get_latest_session(Path.cwd())
        if not session:
            console.print(Text(f'No session found in {Path.cwd()}', style=ColorStyle.ERROR))
            return None
        session = session.create_new_session()
    elif ctx.obj['resume']:
        sessions = Session.load_session_list(Path.cwd())
        if not sessions or len(sessions) == 0:
            console.print(Text(f'No session found in {Path.cwd()}', style=ColorStyle.ERROR))
            return None
        options = []
        for idx, session in enumerate(sessions):
            title_msg = session.get('title_msg', '').replace('\n', ' ')
            message_count = session.get('message_count', 0)
            modified_at = format_relative_time(session.get('updated_at'))
            created_at = format_relative_time(session.get('created_at'))
            option = f'{idx + 1:3}.{modified_at:>12}{created_at:>12}{message_count:>12}  {title_msg}'
            options.append(option)
        header = f'{" " * 4}{"Modified":>12}{"Created":>12}{"# Messages":>12}  Title'
        idx = await user_select(
            options,
            title=header,
        )
        if idx is None:
            return None
        session = Session.load(sessions[idx].get('id'))
    else:
        support_cache_control = 'claude' in ctx.obj['config'].model_name.value.lower()
        session = Session(
            work_dir=Path.cwd(),
            messages=[
                SystemMessage(content=STATIC_SYSTEM_PROMPT, cached=support_cache_control),
                SystemMessage(content=get_system_prompt_dynamic_part(Path.cwd(), ctx.obj['config'].model_name.value)),
            ],
        )
    return session


async def main_async(ctx: typer.Context):
    session = await get_session(ctx)
    if not session:
        return
    agent = await get_main_agent(session, config=ctx.obj['config'], enable_mcp=ctx.obj['mcp'])
    try:
        if ctx.obj['prompt']:
            await agent.headless_run(ctx.obj['prompt'])
        else:
            width, _ = shutil.get_terminal_size()
            has_session = (Path.cwd() / '.klaude' / 'sessions').exists()
            auto_show_logo = not has_session
            console.print(render_hello(show_info=not auto_show_logo))
            if (auto_show_logo or ctx.obj['logo']) and width >= 49:
                console.print()
                console.print(render_logo('KLAUDE', ColorStyle.CLAUDE))
                console.print(render_logo('CODE', ColorStyle.CLAUDE))
            console.print()
            console.print(render_tips())
            try:
                await agent.chat_interactive()
            finally:
                console.print()
                agent.agent_state.print_usage()
                console.print(Text('\nBye!', style=ColorStyle.CLAUDE))
    except KeyboardInterrupt:
        pass


def main_command(
    ctx: typer.Context,
    print_prompt: Optional[str] = typer.Option(None, '-p', '--print', help='Run in headless mode with the given prompt'),
    resume: bool = typer.Option(
        False,
        '-r',
        '--resume',
        help='Resume from an existing session (only for interactive mode)',
    ),
    continue_latest: bool = typer.Option(
        False,
        '-c',
        '--continue',
        help='Continue from the latest session in current directory',
    ),
    config: Optional[str] = typer.Option(None, '--config', help='Specify a config name, e.g. `anthropic` for ~/.klaude/config_anthropic.json, or a path to a config file'),
    api_key: Optional[str] = typer.Option(None, '--api-key', help='Override API key from config'),
    model: Optional[str] = typer.Option(None, '--model', help='Override model name from config'),
    base_url: Optional[str] = typer.Option(None, '--base-url', help='Override base URL from config'),
    max_tokens: Optional[int] = typer.Option(None, '--max-tokens', help='Override max tokens from config'),
    model_azure: Optional[bool] = typer.Option(None, '--model-azure', help='Override model is azure from config'),
    thinking: Optional[bool] = typer.Option(
        None,
        '--thinking',
        help='Enable Claude Extended Thinking capability (only for Anthropic Offical API yet)',
    ),
    api_version: Optional[str] = typer.Option(None, '--api-version', help='Override API version from config'),
    extra_header: Optional[str] = typer.Option(None, '--extra-header', help='Override extra header from config (JSON string)'),
    extra_body: Optional[str] = typer.Option(None, '--extra-body', help='Override extra body from config (JSON string)'),
    theme: Optional[str] = typer.Option(None, '--theme', help='Override theme from config (light, dark, light_ansi, or dark_ansi)'),
    mcp: bool = typer.Option(False, '-m', '--mcp', help='Enable MCP (Model Context Protocol) tools'),
    logo: bool = typer.Option(False, '--logo', help='Show logo'),
    # no_update_check: bool = typer.Option(False, '--no-update-check', help='Skip automatic update check on startup'),
):
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        piped_input = None
        if not sys.stdin.isatty():
            try:
                piped_input = sys.stdin.read().strip()
            except KeyboardInterrupt:
                pass

        if print_prompt is not None and piped_input:
            print_prompt = f'{print_prompt}\n{piped_input}'
        elif print_prompt is None and piped_input:
            print_prompt = piped_input

        try:
            config_manager = setup_config(
                api_key=api_key,
                model_name=model,
                base_url=base_url,
                model_azure=model_azure,
                max_tokens=max_tokens,
                enable_thinking=thinking,
                api_version=api_version,
                extra_header=extra_header,
                extra_body=extra_body,
                theme=theme,
                config_file=config,
            )
            config_model = config_manager.get_config_model()
        except ValueError as e:
            console.print(Text(f'Error: {format_exception(e)}', style=ColorStyle.ERROR))
            raise typer.Exit(code=1)

        ctx.obj['prompt'] = print_prompt
        ctx.obj['resume'] = resume
        ctx.obj['continue_latest'] = continue_latest
        ctx.obj['mcp'] = mcp
        ctx.obj['config'] = config_model
        ctx.obj['logo'] = logo
        # ctx.obj['no_update_check'] = no_update_check
        asyncio.run(main_async(ctx))
