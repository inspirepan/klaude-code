import sys

from ..tui import ColorStyle, Text, console
from ..utils.exception import format_exception
from .arg_parse import parse_command_line


def main():
    try:
        subcommand, args, unknown_args = parse_command_line()
        if subcommand == 'version':
            from .version import version_command

            version_command()
        elif subcommand == 'update':
            from .updater import update_command

            update_command()
        elif subcommand == 'config_show':
            from .config import config_show

            config_show()
        elif subcommand == 'config_edit':
            from .config import config_edit

            config_edit(args.get('config_name'))
        elif subcommand == 'mcp_show':
            from .mcp import mcp_show

            mcp_show()
        elif subcommand == 'mcp_edit':
            from .mcp import mcp_edit

            mcp_edit()
        else:
            from .agent import agent_command

            agent_command(args, unknown_args)

    except KeyboardInterrupt:
        console.print(Text('\nBye!', style=ColorStyle.CLAUDE))
        sys.exit(0)
    except Exception as e:
        console.print(Text(f'Error: {format_exception(e, show_traceback=True)}', style=ColorStyle.ERROR))
        sys.exit(1)
