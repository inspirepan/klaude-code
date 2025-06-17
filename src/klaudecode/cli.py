import asyncio
import os
from typing import Optional

import typer

from .config import create_config_manager
from .input import InputSession
from .message import AIMessage, ToolCallMessage, ToolMessage, UserMessage
from .tui import console, render_hello

app = typer.Typer(help="Coding Agent CLI", add_completion=False)


async def main_async(ctx: typer.Context):
    typer.echo("Coding Agent CLI")
    console.print(UserMessage(content=ctx.obj["config_manager"].get_api_key()))
    console.print(AIMessage(content=ctx.obj["config_manager"].get_model_name()))
    console.print(
        ToolMessage(
            content="/user/bytedance/code",
            tool_call=ToolCallMessage(
                id="1", tool_name="Bash", tool_args="{'command': 'pwd'}", status="error"
            ),
            subagent_tool_calls=[
                ToolCallMessage(
                    id="1",
                    tool_name="Grep",
                    tool_args="{'command': 'pwd'}",
                    status="error",
                )
            ],
        )
    )
    input_session = InputSession(os.getcwd())
    while True:
        user_input = await input_session.prompt_async()
        console.print(user_input)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Option(
        None, "-p", "--print", help="Run in headless mode with the given prompt"
    ),
    resume: bool = typer.Option(
        False,
        "-r",
        "--resume",
        help="Resume from an existing session (only for interactive mode)",
    ),
    continue_latest: bool = typer.Option(
        False,
        "-c",
        "--continue",
        help="Continue from the latest session in current directory",
    ),
    api_key: Optional[str] = typer.Option(
        None, "--api-key", help="Override API key from config"
    ),
    model: Optional[str] = typer.Option(
        None, "--model", help="Override model name from config"
    ),
    base_url: Optional[str] = typer.Option(
        None, "--base-url", help="Override base URL from config"
    ),
    max_tokens: Optional[int] = typer.Option(
        None, "--max-tokens", help="Override max tokens from config"
    ),
    model_azure: Optional[bool] = typer.Option(
        None, "--model-azure", help="Override model is azure from config"
    ),
    no_mcp: bool = typer.Option(
        False, "--no-mcp", help="Disable MCP (Model Context Protocol) loading"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose output"),
):
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        console.print(render_hello())
        config_manager = create_config_manager(
            api_key, model, base_url, model_azure, max_tokens
        )
        ctx.obj["config_manager"] = config_manager
        asyncio.run(main_async(ctx))


config_app = typer.Typer(help="Manage global configuration")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show(ctx: typer.Context):
    config_manager = create_config_manager()
    console.print(config_manager)


@config_app.command("edit")
def config_edit():
    from .config import edit_config_file

    edit_config_file()
