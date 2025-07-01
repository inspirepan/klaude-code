import asyncio
from pathlib import Path
from typing import Optional

import typer

from .agent import get_main_agent
from .config import ConfigManager, ConfigModel
from .message import SystemMessage
from .prompt.system import STATIC_SYSTEM_PROMPT, get_system_prompt_dynamic_part
from .session import Session
from .tui import ColorStyle, Text, console, render_hello
from .user_input import user_select
from .utils.str_utils import format_relative_time

app = typer.Typer(help='Coding Agent CLI', add_completion=False)


def setup_config(**kwargs) -> ConfigModel:
    config_manager = ConfigManager.setup(**kwargs)
    config_model = config_manager.get_config_model()
    if hasattr(config_model, 'theme') and config_model.theme:
        console.set_theme(config_model.theme.value)
    return config_model


async def main_async(ctx: typer.Context):
    if ctx.obj['prompt']:
        # Headless mode
        session = Session(
            Path.cwd(),
            messages=[
                SystemMessage(content=STATIC_SYSTEM_PROMPT, cached=True),
                SystemMessage(content=get_system_prompt_dynamic_part(Path.cwd(), ctx.obj['config'].model_name)),
            ],
        )
        agent = await get_main_agent(session, config=ctx.obj['config'], enable_mcp=ctx.obj['mcp'])
        try:
            await agent.headless_run(ctx.obj['prompt'])
        except KeyboardInterrupt:
            pass
        return

    if ctx.obj['continue_latest']:
        session = Session.get_latest_session(Path.cwd())
        if not session:
            console.print(Text(f'No session found in {Path.cwd()}', style=ColorStyle.ERROR.value))
            return
        session = session.create_new_session()
    elif ctx.obj['resume']:
        sessions = Session.load_session_list(Path.cwd())
        if not sessions or len(sessions) == 0:
            console.print(Text(f'No session found in {Path.cwd()}', style=ColorStyle.ERROR.value))
            return
        options = []
        for idx, session in enumerate(sessions):
            title_msg = session.get('title_msg', '')[:20]
            message_count = session.get('message_count', 0)
            modified_at = format_relative_time(session.get('updated_at'))
            created_at = format_relative_time(session.get('created_at'))

            option = f'{idx + 1:3}.{modified_at:>10}{created_at:>9}{message_count:>12}  {title_msg:<20}'
            options.append(option)

        header = f'{" " * 4}{"Modified":>10}{"Created":>9}{"# Messages":>12}  Title'

        idx = await user_select(
            options,
            title=header,
        )
        if idx is None:
            return
        session = Session.load(sessions[idx].get('id'))
    else:
        session = Session(
            Path.cwd(),
            messages=[
                SystemMessage(content=STATIC_SYSTEM_PROMPT, cached=True),
                SystemMessage(content=get_system_prompt_dynamic_part(Path.cwd(), ctx.obj['config'].model_name)),
            ],
        )
    basic_tips = [
        'type \\ followed by [main]Enter[/main] to insert newlines',
        'type / to choose slash command',
        'type ! to run bash command',
        'type # to memorize',
        'type * to start plan mode',
        'type @ to mention a file',
    ]
    tips = []

    if (Path.cwd() / '.klaude' / 'sessions').exists():
        import random

        tips.append(random.choice(basic_tips))
        tips.append('run [main]klaude --continue[/main] or [main]klaude --resume[/main] to resume a conversation')
    else:
        tips.extend(basic_tips)
    if not (Path.cwd() / 'CLAUDE.md').exists():
        tips.append('run [main]/init[/main] to analyse your codebase')
    if (Path.cwd() / '.klaude' / 'mcp.json').exists():
        tips.append('run [main]klaude --mcp[/main] or [main]/mcp[/main] to enable MCP tools')

    console.print(render_hello(tips))
    agent = await get_main_agent(session, config=ctx.obj['config'], enable_mcp=ctx.obj['mcp'])
    try:
        await agent.chat_interactive()
    except KeyboardInterrupt:
        pass
    finally:
        console.print(Text('\nBye!', style=ColorStyle.AI_MESSAGE.value))


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Option(None, '-p', '--print', help='Run in headless mode with the given prompt'),
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
    mcp: bool = typer.Option(False, '--mcp', help='Enable MCP (Model Context Protocol) tools'),
):
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        try:
            config_model = setup_config(
                api_key=api_key,
                model_name=model,
                base_url=base_url,
                model_azure=model_azure,
                max_tokens=max_tokens,
                enable_thinking=thinking,
                api_version=api_version,
                extra_header=extra_header,
                extra_body=extra_body,
            )
        except ValueError as e:
            console.print(Text(f'Error: {e}', style=ColorStyle.ERROR.value))
            raise typer.Exit(code=1)

        ctx.obj['prompt'] = prompt
        ctx.obj['resume'] = resume
        ctx.obj['continue_latest'] = continue_latest
        ctx.obj['mcp'] = mcp
        ctx.obj['config'] = config_model
        asyncio.run(main_async(ctx))


config_app = typer.Typer(help='Manage global configuration')
app.add_typer(config_app, name='config')


@config_app.command('show')
def config_show(ctx: typer.Context):
    config_manager = ConfigManager.setup()
    console.print(config_manager)


@config_app.command('edit')
def config_edit():
    from .config import GlobalConfigSource

    GlobalConfigSource.edit_config_file()


mcp_app = typer.Typer(help='Manage MCP (Model Context Protocol) servers')
app.add_typer(mcp_app, name='mcp')


@mcp_app.command('show')
def mcp_show():
    """Show current MCP configuration and available tools"""
    import asyncio

    from .mcp.mcp_tool import MCPManager

    _ = setup_config()

    async def show_mcp_info():
        mcp_manager = MCPManager()
        try:
            await mcp_manager.initialize()
            console.print(mcp_manager)
        except Exception as e:
            console.print(Text(f'Error connecting to MCP servers: {e}', style=ColorStyle.ERROR.value))
        finally:
            await mcp_manager.shutdown()

    asyncio.run(show_mcp_info())


@mcp_app.command('edit')
def mcp_edit():
    """Edit MCP configuration file"""
    from .mcp.mcp_config import MCPConfigManager

    config_manager = MCPConfigManager()
    config_manager.edit_config_file()


@app.command('version')
def version_command():
    """Show version information"""
    # Import here to avoid circular imports
    from importlib.metadata import version

    try:
        pkg_version = version('klaude-code')
        console.print(Text(f'klaude-code {pkg_version}', style=ColorStyle.SUCCESS.value))
    except Exception:
        console.print(Text('klaude-code (development)', style=ColorStyle.SUCCESS.value))


@app.command('update')
def update_command():
    """Update klaude-code to the latest version"""
    import subprocess
    import sys

    console.print(Text('Updating klaude-code...', style=ColorStyle.INFO.value))

    try:
        # Try uv first (recommended)
        result = subprocess.run(['uv', 'tool', 'upgrade', 'klaude-code'], capture_output=True, text=True)
        if result.returncode == 0:
            console.print(Text('✓ Updated successfully with uv', style=ColorStyle.SUCCESS.value))
            return
    except FileNotFoundError:
        pass

    try:
        # Fallback to pip
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'klaude-code'], capture_output=True, text=True)
        if result.returncode == 0:
            console.print(Text('✓ Updated successfully with pip', style=ColorStyle.SUCCESS.value))
        else:
            console.print(Text(f'✗ Update failed: {result.stderr}', style=ColorStyle.ERROR.value))
    except Exception as e:
        console.print(Text(f'✗ Update failed: {e}', style=ColorStyle.ERROR.value))
