import typer

from .config import config_app
from .edit import edit_app
from .main import main_command
from .mcp import mcp_app
from .updater import update_app
from .version import version_app

app = typer.Typer(help='Coding Agent CLI', add_completion=False)

app.callback(invoke_without_command=True)(main_command)
app.add_typer(config_app, name='config')
app.add_typer(mcp_app, name='mcp')
app.add_typer(edit_app, name='edit')

for command in version_app.registered_commands:
    app.command(command.name, help=command.help)(command.callback)

for command in update_app.registered_commands:
    app.command(command.name, help=command.help)(command.callback)

__all__ = ['app']
