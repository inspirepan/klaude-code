import asyncio
import os
from typing import Optional

import typer

from .agent import get_main_agent
from .config import ConfigManager
from .prompt import SYSTEM_PROMPT
from .llm import AgentLLM
from .session import Session
from .tui import console, render_hello
from .message import SystemMessage

app = typer.Typer(help='Coding Agent CLI', add_completion=False)


async def main_async(ctx: typer.Context):
    if ctx.obj['continue_latest']:
        session = Session.get_latest_session(os.getcwd()).fork()
        if not session:
            console.print('[red]No session found[/red]')
            return
        session.print_all()
    elif ctx.obj['resume']:
        pass  # TODO
    else:
        session = Session(os.getcwd(), messages=[SystemMessage(content=SYSTEM_PROMPT, cached=True)])  # TODO: repomap
    agent = get_main_agent(session, config=ctx.obj['config'])
    await agent.chat_interactive()


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
    extra_header: Optional[str] = typer.Option(None, '--extra-header', help='Override extra header from config'),
    thinking: Optional[bool] = typer.Option(
        None,
        '--thinking',
        help='Enable Claude Extended Thinking capability (only for Anthropic Offical API)',
    ),
    no_mcp: bool = typer.Option(False, '--no-mcp', help='Disable MCP (Model Context Protocol) loading'),
    verbose: bool = typer.Option(False, '--verbose', help='Enable verbose output'),
):
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        console.print(render_hello())
        config_manager = ConfigManager.setup(
            api_key=api_key,
            model_name=model,
            base_url=base_url,
            model_azure=model_azure,
            max_tokens=max_tokens,
            extra_header=extra_header,
            enable_thinking=thinking,
        )
        ctx.obj['resume'] = resume
        ctx.obj['continue_latest'] = continue_latest
        ctx.obj['no_mcp'] = no_mcp
        ctx.obj['verbose'] = verbose
        ctx.obj['config'] = config_manager.get_config_model()
        AgentLLM.initialize(
            model_name=config_manager.get('model_name'),
            base_url=config_manager.get('base_url'),
            api_key=config_manager.get('api_key'),
            model_azure=config_manager.get('model_azure'),
            max_tokens=config_manager.get('max_tokens'),
            extra_header=config_manager.get('extra_header'),
            enable_thinking=config_manager.get('enable_thinking'),
        )
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
