"""
Argument parsing
"""

import argparse
from typing import Any, Dict, List, Optional, Tuple


class ArgumentParser:
    """
    Custom argument parser.

    Typer is not used because we need to treat unknown arguments as chat queries.
    """

    def __init__(self):
        self.parser = argparse.ArgumentParser(
            prog='klaude',
            description='Coding Agent CLI',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            add_help=False,  # We'll handle help ourselves
        )
        self._setup_main_parser()

    def _setup_main_parser(self):
        self.parser.add_argument('-h', '--help', action='store_true')

        self.parser.add_argument('-p', '--print', dest='headless_prompt')  # Headless mode

        self.parser.add_argument('-r', '--resume', action='store_true')  # Resume from an existing session (only for interactive mode)

        self.parser.add_argument('-c', '--continue', dest='continue_latest', action='store_true')  # Continue from the latest session in current directory

        self.parser.add_argument('-f', '--config')  # Specify a config name to run, e.g. `anthropic` for `~/.klaude/config_anthropic.json`, or a path to a config file

        self.parser.add_argument('--api-key')  # Override API key from config

        self.parser.add_argument('--model')  # Override model name from config

        self.parser.add_argument('--base-url')  # Override base URL from config

        self.parser.add_argument('--max-tokens', type=int)  # Override max tokens from config

        self.parser.add_argument('--model-azure', action='store_const', const=True, default=None)  # Override model is azure from config

        self.parser.add_argument('--thinking', action='store_const', const=True, default=None)  # Enable Claude Extended Thinking capability (only for Anthropic Offical API yet)

        self.parser.add_argument('--api-version')  # Override API version from config

        self.parser.add_argument('--extra-header')  # Override extra header from config (JSON string)

        self.parser.add_argument('--extra-body')  # Override extra body from config (JSON string)

        self.parser.add_argument('--theme')  # Override theme from config (light, dark, light_ansi, or dark_ansi)

        self.parser.add_argument('-m', '--mcp', action='store_true')  # Enable MCP tools

        self.parser.add_argument('--logo', action='store_true')  # Show ASCII Art logo

        self.parser.add_argument('unknown_args', nargs='*')  # Unknown arguments

    def parse_args(self, args: Optional[List[str]] = None) -> Tuple[Dict[str, Any], List[str]]:
        parsed_args, unknown_args = self.parser.parse_known_args(args)

        parsed_dict = vars(parsed_args)

        if parsed_dict.get('unknown_args'):
            unknown_args.extend(parsed_dict['unknown_args'])

        return parsed_dict, unknown_args

    def print_help(self):
        import sys

        help_text = """
usage: klaude [OPTIONS] [SUBCOMMAND] [ARGS...]

Coding Agent CLI

Options:
  -h, --help            Show this help message and exit
  -p, --print PROMPT    Run in headless mode with the given prompt
  -r, --resume          Resume from an existing session (only for interactive mode)
  -c, --continue        Continue from the latest session in current directory
  -f, --config CONFIG   Specify a config name to run, e.g. `anthropic` for `~/.klaude/config_anthropic.json`, or a path to a config file
  --api-key KEY         Override API key from config
  --model MODEL         Override model name from config
  --base-url URL        Override base URL from config
  --max-tokens TOKENS   Override max tokens from config
  --model-azure         Override model is azure from config
  --thinking            Enable Claude Extended Thinking capability (only for Anthropic Offical API yet)
  --api-version VERSION Override API version from config
  --extra-header HEADER Override extra header from config (JSON string)
  --extra-body BODY     Override extra body from config (JSON string)
  --theme THEME         Override theme from config (light, dark, light_ansi, or dark_ansi)
  -m, --mcp             Enable MCP tools
  --logo                Show ASCII Art logo

Subcommands:
  config                Show all configurations
    edit [CONFIG_NAME]  Edit configuration file

  mcp                   Show MCP (Model Context Protocol) servers
    edit                Edit MCP configuration file

  edit                  Alias for `config edit` and `mcp edit`
  edit [CONFIG_NAME]    Edit configuration files, none for default config.json
  edit mcp              Edit MCP configuration file

  version               Show version information

  update                Update klaude-code to the latest version

Examples:
  klaude                        # Start interactive mode
  klaude -p "Hello, world!"     # Run with prompt
  klaude -f anthropic           # Use specific config
  klaude config show            # Show all configurations
  klaude config edit            # Show all configurations
  klaude config edit anthropic  # Edit anthropic config
  klaude mcp show               # Show MCP configuration
  klaude update                 # Update to latest version
"""
        print(help_text.strip())
        sys.exit(0)


def parse_command_line(args: Optional[List[str]] = None) -> Tuple[str, Dict[str, Any], List[str]]:
    parser = ArgumentParser()
    parsed_args, unknown_args = parser.parse_args(args)

    subcommand = unknown_args[0] if unknown_args else ''
    unknown_args = unknown_args[1:]

    if parsed_args.get('help') or subcommand == 'help':
        parser.print_help()
        return 'help', parsed_args, unknown_args

    if subcommand == 'config':
        return parse_config_subcommand(unknown_args, parsed_args)
    elif subcommand == 'mcp':
        return parse_mcp_subcommand(unknown_args, parsed_args)
    elif subcommand == 'edit':
        return parse_edit_subcommand(unknown_args, parsed_args)
    elif subcommand == 'version':
        return 'version', parsed_args, []
    elif subcommand == 'update':
        return 'update', parsed_args, []
    else:
        if subcommand:
            unknown_args.insert(0, subcommand)
        return 'main', parsed_args, unknown_args


def parse_config_subcommand(unknown_args: List[str], parsed_args: Dict[str, Any]) -> Tuple[str, Dict[str, Any], List[str]]:
    if not unknown_args:
        return 'config_show', parsed_args, []

    config_action = unknown_args[0]
    remaining_args = unknown_args[1:]

    if config_action == 'edit':
        config_name = remaining_args[0] if remaining_args else None
        parsed_args['config_name'] = config_name
        return 'config_edit', parsed_args, []
    else:
        return 'config_show', parsed_args, []


def parse_mcp_subcommand(unknown_args: List[str], parsed_args: Dict[str, Any]) -> Tuple[str, Dict[str, Any], List[str]]:
    if not unknown_args:
        return 'mcp_show', parsed_args, []

    mcp_action = unknown_args[0]

    if mcp_action == 'edit':
        return 'mcp_edit', parsed_args, []
    else:
        return 'mcp_show', parsed_args, []


def parse_edit_subcommand(unknown_args: List[str], parsed_args: Dict[str, Any]) -> Tuple[str, Dict[str, Any], List[str]]:
    if not unknown_args:
        return 'config_edit', parsed_args, []

    edit_action = unknown_args[0] if unknown_args else ''

    if edit_action == 'mcp':
        return 'mcp_edit', parsed_args, []
    else:
        config_name = edit_action
        parsed_args['config_name'] = config_name
        return 'config_edit', parsed_args, []
