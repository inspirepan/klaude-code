"""
Argument parsing
"""

import argparse
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, Field


class CLIArgs(BaseModel):
    """CLI arguments parsed into Pydantic model"""

    # Main options
    help: Annotated[bool, Field(description='Show help message and exit')] = False
    headless_prompt: Annotated[Optional[str], Field(description='Run in headless mode with the given prompt')] = None
    resume: Annotated[bool, Field(description='Resume from an existing session (only for interactive mode)')] = False
    continue_latest: Annotated[bool, Field(description='Continue from the latest session in current directory')] = False
    config: Annotated[Optional[str], Field(description='Specify a config name to run or path to a config file')] = None

    # API overrides
    api_key: Annotated[Optional[str], Field(description='Override API key from config')] = None
    model: Annotated[Optional[str], Field(description='Override model name from config')] = None
    base_url: Annotated[Optional[str], Field(description='Override base URL from config')] = None
    max_tokens: Annotated[Optional[int], Field(description='Override max tokens from config')] = None
    model_azure: Annotated[Optional[bool], Field(description='Override model is azure from config')] = None
    thinking: Annotated[Optional[bool], Field(description='Enable Claude Extended Thinking capability')] = None
    api_version: Annotated[Optional[str], Field(description='Override API version from config')] = None
    extra_header: Annotated[Optional[str], Field(description='Override extra header from config (JSON string)')] = None
    extra_body: Annotated[Optional[str], Field(description='Override extra body from config (JSON string)')] = None

    # UI options
    theme: Annotated[Optional[Literal['light', 'dark', 'light_ansi', 'dark_ansi']], Field(description='Override theme from config')] = None
    logo: Annotated[bool, Field(description='Show ASCII Art logo')] = False

    # MCP
    mcp: Annotated[bool, Field(description='Enable MCP tools')] = False


class ParsedCommand(BaseModel):
    """Result of command line parsing"""

    command: Annotated[str, Field(description='The command to execute')]
    args: Annotated[CLIArgs, Field(description='Parsed CLI arguments')]
    unknown_args: Annotated[List[str], Field(description='Unknown arguments (treated as chat input)')] = []
    config_name: Annotated[Optional[str], Field(description='Config name for edit commands')] = None


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

    def parse_args(self, args: Optional[List[str]] = None) -> CLIArgs:
        """Parse command line arguments into Pydantic model"""
        parsed_args, unknown_args = self.parser.parse_known_args(args)
        parsed_dict = vars(parsed_args)

        # Handle unknown_args from positional argument
        if parsed_dict.get('unknown_args'):
            unknown_args.extend(parsed_dict['unknown_args'])

        # Remove unknown_args from dict since it's not part of CLIArgs
        parsed_dict.pop('unknown_args', None)

        # Create CLIArgs model, storing unknown_args separately for later processing
        cli_args = CLIArgs(**parsed_dict)
        cli_args._unknown_args = unknown_args  # Store temporarily

        return cli_args

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


def parse_command_line(args: Optional[List[str]] = None) -> ParsedCommand:
    """Parse command line and return structured command result"""
    parser = ArgumentParser()
    cli_args = parser.parse_args(args)

    # Extract unknown args from temporary storage
    unknown_args = getattr(cli_args, '_unknown_args', [])
    delattr(cli_args, '_unknown_args')  # Clean up temporary attribute

    # Extract subcommand from unknown args
    subcommand = unknown_args[0] if unknown_args else ''
    remaining_unknown = unknown_args[1:] if unknown_args else []

    if cli_args.help or subcommand == 'help':
        parser.print_help()
        return ParsedCommand(command='help', args=cli_args, unknown_args=remaining_unknown)

    if subcommand == 'config':
        return _parse_config_subcommand(remaining_unknown, cli_args)
    elif subcommand == 'mcp':
        return _parse_mcp_subcommand(remaining_unknown, cli_args)
    elif subcommand == 'edit':
        return _parse_edit_subcommand(remaining_unknown, cli_args)
    elif subcommand == 'version':
        return ParsedCommand(command='version', args=cli_args, unknown_args=[])
    elif subcommand == 'update':
        return ParsedCommand(command='update', args=cli_args, unknown_args=[])
    else:
        if subcommand:
            remaining_unknown.insert(0, subcommand)
        return ParsedCommand(command='main', args=cli_args, unknown_args=remaining_unknown)


def _parse_config_subcommand(unknown_args: List[str], cli_args: CLIArgs) -> ParsedCommand:
    """Parse config subcommand"""
    if not unknown_args:
        return ParsedCommand(command='config_show', args=cli_args, unknown_args=[])

    config_action = unknown_args[0]
    remaining_args = unknown_args[1:]

    if config_action == 'edit':
        config_name = remaining_args[0] if remaining_args else None
        return ParsedCommand(command='config_edit', args=cli_args, unknown_args=[], config_name=config_name)
    else:
        return ParsedCommand(command='config_show', args=cli_args, unknown_args=[])


def _parse_mcp_subcommand(unknown_args: List[str], cli_args: CLIArgs) -> ParsedCommand:
    """Parse MCP subcommand"""
    if not unknown_args:
        return ParsedCommand(command='mcp_show', args=cli_args, unknown_args=[])

    mcp_action = unknown_args[0]

    if mcp_action == 'edit':
        return ParsedCommand(command='mcp_edit', args=cli_args, unknown_args=[])
    else:
        return ParsedCommand(command='mcp_show', args=cli_args, unknown_args=[])


def _parse_edit_subcommand(unknown_args: List[str], cli_args: CLIArgs) -> ParsedCommand:
    """Parse edit subcommand"""
    if not unknown_args:
        return ParsedCommand(command='config_edit', args=cli_args, unknown_args=[])

    edit_action = unknown_args[0] if unknown_args else ''

    if edit_action == 'mcp':
        return ParsedCommand(command='mcp_edit', args=cli_args, unknown_args=[])
    else:
        config_name = edit_action
        return ParsedCommand(command='config_edit', args=cli_args, unknown_args=[], config_name=config_name)
