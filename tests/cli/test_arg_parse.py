"""
Tests for CLI argument parsing functionality.
"""

from unittest.mock import patch

from klaudecode.cli.arg_parse import ArgumentParser, CLIArgs, ParsedCommand, parse_command_line


class TestArgumentParser:
    """Test ArgumentParser class."""

    def test_init(self):
        parser = ArgumentParser()
        assert parser.parser.prog == 'klaude'
        assert parser.parser.description == 'Coding Agent CLI'
        assert not parser.parser.add_help

    def test_parse_args_empty(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args([])

        assert isinstance(cli_args, CLIArgs)
        assert cli_args.help is False
        assert cli_args.headless_prompt is None
        assert cli_args.resume is False
        assert cli_args.continue_latest is False
        assert cli_args.config is None

    def test_parse_args_help_short(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-h'])

        assert cli_args.help is True

    def test_parse_args_help_long(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--help'])

        assert cli_args.help is True

    def test_parse_args_headless_short(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-p', 'test prompt'])

        assert cli_args.headless_prompt == 'test prompt'

    def test_parse_args_headless_long(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--print', 'test prompt'])

        assert cli_args.headless_prompt == 'test prompt'

    def test_parse_args_resume_short(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-r'])

        assert cli_args.resume is True

    def test_parse_args_resume_long(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--resume'])

        assert cli_args.resume is True

    def test_parse_args_continue_short(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-c'])

        assert cli_args.continue_latest is True

    def test_parse_args_continue_long(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--continue'])

        assert cli_args.continue_latest is True

    def test_parse_args_config_short(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-f', 'anthropic'])

        assert cli_args.config == 'anthropic'

    def test_parse_args_config_long(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--config', 'anthropic'])

        assert cli_args.config == 'anthropic'

    def test_parse_args_api_key(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--api-key', 'sk-test123'])

        assert cli_args.api_key == 'sk-test123'

    def test_parse_args_model(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--model', 'claude-3-sonnet'])

        assert cli_args.model == 'claude-3-sonnet'

    def test_parse_args_base_url(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--base-url', 'https://api.test.com'])

        assert cli_args.base_url == 'https://api.test.com'

    def test_parse_args_max_tokens(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--max-tokens', '1000'])

        assert cli_args.max_tokens == 1000

    def test_parse_args_model_azure(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--model-azure'])

        assert cli_args.model_azure is True

    def test_parse_args_thinking(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--thinking'])

        assert cli_args.thinking is True

    def test_parse_args_api_version(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--api-version', '2023-12-01'])

        assert cli_args.api_version == '2023-12-01'

    def test_parse_args_extra_header(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--extra-header', '{"X-Custom": "value"}'])

        assert cli_args.extra_header == '{"X-Custom": "value"}'

    def test_parse_args_extra_body(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--extra-body', '{"custom": "data"}'])

        assert cli_args.extra_body == '{"custom": "data"}'

    def test_parse_args_theme(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--theme', 'dark'])

        assert cli_args.theme == 'dark'

    def test_parse_args_mcp_short(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-m'])

        assert cli_args.mcp is True

    def test_parse_args_mcp_long(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--mcp'])

        assert cli_args.mcp is True

    def test_parse_args_logo(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--logo'])

        assert cli_args.logo is True

    def test_parse_args_combined_flags(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-h', '-r', '-c', '--mcp', '--logo'])

        assert cli_args.help is True
        assert cli_args.resume is True
        assert cli_args.continue_latest is True
        assert cli_args.mcp is True
        assert cli_args.logo is True

    def test_parse_args_combined_values(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-p', 'test prompt', '-f', 'anthropic', '--model', 'claude-3'])

        assert cli_args.headless_prompt == 'test prompt'
        assert cli_args.config == 'anthropic'
        assert cli_args.model == 'claude-3'

    def test_parse_args_all_overrides(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['--api-key', 'test-key', '--base-url', 'https://api.test.com', '--max-tokens', '1000', '--model-azure', '--thinking', '--theme', 'dark'])

        assert cli_args.api_key == 'test-key'
        assert cli_args.base_url == 'https://api.test.com'
        assert cli_args.max_tokens == 1000
        assert cli_args.model_azure is True
        assert cli_args.thinking is True
        assert cli_args.theme == 'dark'

    def test_parse_args_unknown_handling(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['unknown', 'args', 'here'])

        unknown_args = getattr(cli_args, '_unknown_args', [])
        assert unknown_args == ['unknown', 'args', 'here']

    def test_parse_args_mixed_known_unknown(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['-f', 'anthropic', 'unknown', 'args'])

        assert cli_args.config == 'anthropic'
        unknown_args = getattr(cli_args, '_unknown_args', [])
        assert unknown_args == ['unknown', 'args']

    def test_parse_args_unknown_args_in_parsed(self):
        parser = ArgumentParser()
        cli_args = parser.parse_args(['test1', 'test2'])

        unknown_args = getattr(cli_args, '_unknown_args', [])
        assert 'test1' in unknown_args
        assert 'test2' in unknown_args

    @patch('rich.console.Console.print')
    @patch('sys.exit')
    def test_print_help(self, mock_exit, mock_print):
        parser = ArgumentParser()
        parser.print_help()

        mock_print.assert_called_once()
        mock_exit.assert_called_once_with(0)

        help_text = mock_print.call_args[0][0]
        assert '[bold green]Usage:[/bold green]' in help_text
        assert '[cyan bold]-h, --help[/cyan bold]' in help_text
        assert '[cyan bold]-p, --print[/cyan bold]' in help_text
        assert '[cyan bold]-r, --resume[/cyan bold]' in help_text
        assert '[cyan bold]-c, --continue[/cyan bold]' in help_text
        assert '[cyan bold]-f, --config[/cyan bold]' in help_text
        assert '[cyan bold]--api-key[/cyan bold]' in help_text
        assert '[cyan bold]--model[/cyan bold]' in help_text
        assert '[cyan bold]--base-url[/cyan bold]' in help_text
        assert '[cyan bold]--max-tokens[/cyan bold]' in help_text
        assert '--model-azure' in help_text
        assert '--thinking' in help_text
        assert '--api-version' in help_text
        assert '--extra-header' in help_text
        assert '--extra-body' in help_text
        assert '--theme' in help_text
        assert '-m, --mcp' in help_text
        assert '--logo' in help_text


class TestParseCommandLine:
    """Test parse_command_line function."""

    @patch('builtins.print')
    @patch('sys.exit')
    def test_parse_command_line_help_short(self, mock_exit, mock_print):
        result = parse_command_line(['-h'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'help'

    @patch('builtins.print')
    @patch('sys.exit')
    def test_parse_command_line_help_subcommand(self, mock_exit, mock_print):
        result = parse_command_line(['help'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'help'

    def test_parse_command_line_config(self):
        result = parse_command_line(['config'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'config_show'

    def test_parse_command_line_mcp(self):
        result = parse_command_line(['mcp'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'mcp_show'

    def test_parse_command_line_edit(self):
        result = parse_command_line(['edit'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'config_edit'

    def test_parse_command_line_version(self):
        result = parse_command_line(['version'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'version'

    def test_parse_command_line_update(self):
        result = parse_command_line(['update'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'update'

    def test_parse_command_line_main_empty(self):
        result = parse_command_line([])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'main'

    def test_parse_command_line_main_unknown(self):
        result = parse_command_line(['unknown', 'args'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'main'
        assert result.unknown_args == ['unknown', 'args']

    def test_parse_command_line_main_with_flags(self):
        result = parse_command_line(['-f', 'anthropic', 'chat', 'message'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'main'
        assert result.args.config == 'anthropic'
        assert result.unknown_args == ['chat', 'message']

    def test_parse_command_line_none_args(self):
        result = parse_command_line(None)
        assert isinstance(result, ParsedCommand)
        assert result.command == 'main'

    def test_config_edit_with_name(self):
        result = parse_command_line(['config', 'edit', 'anthropic'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'config_edit'
        assert result.config_name == 'anthropic'

    def test_config_edit_without_name(self):
        result = parse_command_line(['config', 'edit'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'config_edit'
        assert result.config_name is None

    def test_mcp_edit(self):
        result = parse_command_line(['mcp', 'edit'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'mcp_edit'

    def test_edit_mcp(self):
        result = parse_command_line(['edit', 'mcp'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'mcp_edit'

    def test_edit_with_config_name(self):
        result = parse_command_line(['edit', 'anthropic'])
        assert isinstance(result, ParsedCommand)
        assert result.command == 'config_edit'
        assert result.config_name == 'anthropic'
