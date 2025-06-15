import typer

from .message import ToolMessage, AIMessage, UserMessage, SystemMessage, ToolCallMessage
from .tui import console

app = typer.Typer(help="Coding Agent CLI", add_completion=False)


@app.callback(invoke_without_command=True)
def main(
        ctx: typer.Context,):
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand is None:
        typer.echo("Coding Agent CLI")
        console.print(UserMessage(content="Hello, world!"))
        console.print(AIMessage(content="Hello, world!"))
        console.print(ToolMessage(content="/user/bytedance/code", tool_call=ToolCallMessage(id="1", tool_name="Bash", tool_args="{'command': 'pwd'}", status="error")))
