"""
Tests for CLI argument parsing functionality.
"""

from unittest.mock import patch

from klaudecode.cli.arg_parse import (
    ArgumentParser,
    parse_command_line,
    parse_config_subcommand,
    parse_mcp_subcommand,
    parse_edit_subcommand,
)


class TestArgumentParser:
    """Test ArgumentParser class."""

    def test_init(self):
        parser = ArgumentParser()
        assert parser.parser.prog == 'klaude'
        assert parser.parser.description == 'Coding Agent CLI'
        assert not parser.parser.add_help

    def test_parse_args_empty(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args([])

        assert parsed_dict['help'] is False
        assert parsed_dict['headless_prompt'] is None
        assert parsed_dict['resume'] is False
        assert parsed_dict['continue_latest'] is False
        assert parsed_dict['config'] is None
        assert unknown_args == []

    def test_parse_args_help_short(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['-h'])

        assert parsed_dict['help'] is True
        assert unknown_args == []

    def test_parse_args_help_long(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--help'])

        assert parsed_dict['help'] is True
        assert unknown_args == []

    def test_parse_args_headless_short(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['-p', 'test prompt'])

        assert parsed_dict['headless_prompt'] == 'test prompt'
        assert unknown_args == []

    def test_parse_args_headless_long(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--print', 'test prompt'])

        assert parsed_dict['headless_prompt'] == 'test prompt'
        assert unknown_args == []

    def test_parse_args_resume_short(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['-r'])

        assert parsed_dict['resume'] is True
        assert unknown_args == []

    def test_parse_args_resume_long(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--resume'])

        assert parsed_dict['resume'] is True
        assert unknown_args == []

    def test_parse_args_continue_short(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['-c'])

        assert parsed_dict['continue_latest'] is True
        assert unknown_args == []

    def test_parse_args_continue_long(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--continue'])

        assert parsed_dict['continue_latest'] is True
        assert unknown_args == []

    def test_parse_args_config_short(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['-f', 'anthropic'])

        assert parsed_dict['config'] == 'anthropic'
        assert unknown_args == []

    def test_parse_args_config_long(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--config', 'anthropic'])

        assert parsed_dict['config'] == 'anthropic'
        assert unknown_args == []

    def test_parse_args_api_key(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--api-key', 'sk-test123'])

        assert parsed_dict['api_key'] == 'sk-test123'
        assert unknown_args == []

    def test_parse_args_model(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--model', 'claude-3-sonnet'])

        assert parsed_dict['model'] == 'claude-3-sonnet'
        assert unknown_args == []

    def test_parse_args_base_url(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--base-url', 'https://api.example.com'])

        assert parsed_dict['base_url'] == 'https://api.example.com'
        assert unknown_args == []

    def test_parse_args_max_tokens(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--max-tokens', '4096'])

        assert parsed_dict['max_tokens'] == 4096
        assert unknown_args == []

    def test_parse_args_model_azure(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--model-azure'])

        assert parsed_dict['model_azure'] is True
        assert unknown_args == []

    def test_parse_args_thinking(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--thinking'])

        assert parsed_dict['thinking'] is True
        assert unknown_args == []

    def test_parse_args_api_version(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--api-version', '2023-05-15'])

        assert parsed_dict['api_version'] == '2023-05-15'
        assert unknown_args == []

    def test_parse_args_extra_header(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--extra-header', '{"X-Custom": "value"}'])

        assert parsed_dict['extra_header'] == '{"X-Custom": "value"}'
        assert unknown_args == []

    def test_parse_args_extra_body(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--extra-body', '{"custom": true}'])

        assert parsed_dict['extra_body'] == '{"custom": true}'
        assert unknown_args == []

    def test_parse_args_theme(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--theme', 'dark'])

        assert parsed_dict['theme'] == 'dark'
        assert unknown_args == []

    def test_parse_args_mcp_short(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['-m'])

        assert parsed_dict['mcp'] is True
        assert unknown_args == []

    def test_parse_args_mcp_long(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--mcp'])

        assert parsed_dict['mcp'] is True
        assert unknown_args == []

    def test_parse_args_logo(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--logo'])

        assert parsed_dict['logo'] is True
        assert unknown_args == []

    def test_parse_args_unknown_args(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['unknown', 'args', 'here'])

        assert unknown_args == ['unknown', 'args', 'here']

    def test_parse_args_mixed_known_unknown(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['-f', 'anthropic', 'unknown', 'args'])

        assert parsed_dict['config'] == 'anthropic'
        assert unknown_args == ['unknown', 'args']

    def test_parse_args_unknown_args_in_parsed(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['test1', 'test2'])

        assert 'test1' in unknown_args
        assert 'test2' in unknown_args

    @patch('builtins.print')
    @patch('sys.exit')
    def test_print_help(self, mock_exit, mock_print):
        parser = ArgumentParser()
        parser.print_help()

        mock_print.assert_called_once()
        mock_exit.assert_called_once_with(0)

        help_text = mock_print.call_args[0][0]
        assert 'usage: klaude [OPTIONS] [SUBCOMMAND] [ARGS...]' in help_text
        assert 'Coding Agent CLI' in help_text
        assert '-h, --help' in help_text
        assert '-p, --print' in help_text
        assert '-r, --resume' in help_text
        assert '-c, --continue' in help_text
        assert '-f, --config' in help_text
        assert '--api-key' in help_text
        assert '--model' in help_text
        assert '--base-url' in help_text
        assert '--max-tokens' in help_text
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

    @patch('klaudecode.cli.arg_parse.ArgumentParser.print_help')
    def test_parse_command_line_help_flag(self, mock_print_help):
        subcommand, parsed_args, unknown_args = parse_command_line(['-h'])

        assert subcommand == 'help'
        mock_print_help.assert_called_once()

    @patch('klaudecode.cli.arg_parse.ArgumentParser.print_help')
    def test_parse_command_line_help_subcommand(self, mock_print_help):
        subcommand, parsed_args, unknown_args = parse_command_line(['help'])

        assert subcommand == 'help'
        mock_print_help.assert_called_once()

    def test_parse_command_line_config_subcommand(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['config'])

        assert subcommand == 'config_show'
        assert unknown_args == []

    def test_parse_command_line_mcp_subcommand(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['mcp'])

        assert subcommand == 'mcp_show'
        assert unknown_args == []

    def test_parse_command_line_edit_subcommand(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['edit'])

        assert subcommand == 'config_edit'
        assert unknown_args == []

    def test_parse_command_line_version_subcommand(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['version'])

        assert subcommand == 'version'
        assert unknown_args == []

    def test_parse_command_line_update_subcommand(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['update'])

        assert subcommand == 'update'
        assert unknown_args == []

    def test_parse_command_line_main_no_args(self):
        subcommand, parsed_args, unknown_args = parse_command_line([])

        assert subcommand == 'main'
        assert unknown_args == []

    def test_parse_command_line_main_with_unknown_subcommand(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['unknown', 'args'])

        assert subcommand == 'main'
        assert unknown_args == ['unknown', 'args']

    def test_parse_command_line_main_with_args(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['-f', 'anthropic', 'chat', 'message'])

        assert subcommand == 'main'
        assert parsed_args['config'] == 'anthropic'
        assert unknown_args == ['chat', 'message']

    def test_parse_command_line_none_args(self):
        subcommand, parsed_args, unknown_args = parse_command_line(None)

        assert subcommand == 'main'


class TestParseConfigSubcommand:
    """Test parse_config_subcommand function."""

    def test_parse_config_subcommand_no_args(self):
        subcommand, parsed_args, unknown_args = parse_config_subcommand([], {})

        assert subcommand == 'config_show'
        assert unknown_args == []

    def test_parse_config_subcommand_edit_no_name(self):
        subcommand, parsed_args, unknown_args = parse_config_subcommand(['edit'], {})

        assert subcommand == 'config_edit'
        assert parsed_args['config_name'] is None
        assert unknown_args == []

    def test_parse_config_subcommand_edit_with_name(self):
        subcommand, parsed_args, unknown_args = parse_config_subcommand(['edit', 'anthropic'], {})

        assert subcommand == 'config_edit'
        assert parsed_args['config_name'] == 'anthropic'
        assert unknown_args == []

    def test_parse_config_subcommand_unknown_action(self):
        subcommand, parsed_args, unknown_args = parse_config_subcommand(['unknown'], {})

        assert subcommand == 'config_show'
        assert unknown_args == []


class TestParseOtherSubcommands:
    """Test other subcommand parsing functions."""

    def test_parse_mcp_subcommand_no_args(self):
        subcommand, parsed_args, unknown_args = parse_mcp_subcommand([], {})

        assert subcommand == 'mcp_show'
        assert unknown_args == []

    def test_parse_mcp_subcommand_edit(self):
        subcommand, parsed_args, unknown_args = parse_mcp_subcommand(['edit'], {})

        assert subcommand == 'mcp_edit'
        assert unknown_args == []

    def test_parse_mcp_subcommand_unknown_action(self):
        subcommand, parsed_args, unknown_args = parse_mcp_subcommand(['unknown'], {})

        assert subcommand == 'mcp_show'
        assert unknown_args == []

    def test_parse_edit_subcommand_no_args(self):
        subcommand, parsed_args, unknown_args = parse_edit_subcommand([], {})

        assert subcommand == 'config_edit'
        assert unknown_args == []

    def test_parse_edit_subcommand_mcp(self):
        subcommand, parsed_args, unknown_args = parse_edit_subcommand(['mcp'], {})

        assert subcommand == 'mcp_edit'
        assert unknown_args == []

    def test_parse_edit_subcommand_config_name(self):
        subcommand, parsed_args, unknown_args = parse_edit_subcommand(['anthropic'], {})

        assert subcommand == 'config_edit'
        assert parsed_args['config_name'] == 'anthropic'
        assert unknown_args == []


class TestComplexArguments:
    """Test complex argument combinations."""

    def test_multiple_flags(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['-r', '--mcp', '--logo'])

        assert subcommand == 'main'
        assert parsed_args['resume'] is True
        assert parsed_args['mcp'] is True
        assert parsed_args['logo'] is True
        assert unknown_args == []

    def test_config_with_override_args(self):
        subcommand, parsed_args, unknown_args = parse_command_line(
            ['-f', 'anthropic', '--api-key', 'sk-test', '--model', 'claude-3-opus', '--max-tokens', '8192', 'chat', 'prompt']
        )

        assert subcommand == 'main'
        assert parsed_args['config'] == 'anthropic'
        assert parsed_args['api_key'] == 'sk-test'
        assert parsed_args['model'] == 'claude-3-opus'
        assert parsed_args['max_tokens'] == 8192
        assert unknown_args == ['chat', 'prompt']

    def test_headless_with_args(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['-p', 'Hello world', '--thinking', '--theme', 'dark'])

        assert subcommand == 'main'
        assert parsed_args['headless_prompt'] == 'Hello world'
        assert parsed_args['thinking'] is True
        assert parsed_args['theme'] == 'dark'
        assert unknown_args == []

    def test_azure_config(self):
        subcommand, parsed_args, unknown_args = parse_command_line(
            ['--model-azure', '--api-version', '2023-05-15', '--base-url', 'https://myazure.openai.azure.com', '--extra-header', '{"Authorization": "Bearer token"}']
        )

        assert subcommand == 'main'
        assert parsed_args['model_azure'] is True
        assert parsed_args['api_version'] == '2023-05-15'
        assert parsed_args['base_url'] == 'https://myazure.openai.azure.com'
        assert parsed_args['extra_header'] == '{"Authorization": "Bearer token"}'
        assert unknown_args == []

    def test_subcommand_with_options(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['--logo', 'config', 'edit', 'anthropic'])

        assert subcommand == 'config_edit'
        assert parsed_args['logo'] is True
        assert parsed_args['config_name'] == 'anthropic'
        assert unknown_args == []


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_string_args(self):
        subcommand, parsed_args, unknown_args = parse_command_line([''])

        assert subcommand == 'main'
        assert unknown_args == []

    def test_special_characters_in_args(self):
        subcommand, parsed_args, unknown_args = parse_command_line(['--model', 'claude-3.5-sonnet', 'special@chars#here'])

        assert subcommand == 'main'
        assert parsed_args['model'] == 'claude-3.5-sonnet'
        assert unknown_args == ['special@chars#here']

    def test_numeric_max_tokens_validation(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args(['--max-tokens', '1000'])

        assert parsed_dict['max_tokens'] == 1000
        assert isinstance(parsed_dict['max_tokens'], int)

    def test_boolean_flags_default_values(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args([])

        assert parsed_dict['help'] is False
        assert parsed_dict['resume'] is False
        assert parsed_dict['continue_latest'] is False
        assert parsed_dict['mcp'] is False
        assert parsed_dict['logo'] is False
        assert parsed_dict['model_azure'] is None
        assert parsed_dict['thinking'] is None

    def test_none_values_for_optional_args(self):
        parser = ArgumentParser()
        parsed_dict, unknown_args = parser.parse_args([])

        assert parsed_dict['headless_prompt'] is None
        assert parsed_dict['config'] is None
        assert parsed_dict['api_key'] is None
        assert parsed_dict['model'] is None
        assert parsed_dict['base_url'] is None
        assert parsed_dict['max_tokens'] is None
        assert parsed_dict['api_version'] is None
        assert parsed_dict['extra_header'] is None
        assert parsed_dict['extra_body'] is None
        assert parsed_dict['theme'] is None
