import json
import subprocess
import time
from collections import Counter
from typing import Generator

from rich.abc import RichRenderable
from rich.console import Group
from rich.text import Text

from ..agent import AgentState
from ..llm.llm_proxy_anthropic import AnthropicProxy
from ..message import UserMessage
from ..tui import ColorStyle, render_suffix
from ..user_input import Command, CommandHandleOutput, UserInput, user_select


class DebugCommand(Command):
    def get_name(self) -> str:
        return 'debug'

    def get_command_desc(self) -> str:
        return 'Export session messages and tools in native OpenAI/Anthropic API schema format for debugging and direct API usage'

    async def handle(self, agent_state: 'AgentState', user_input: UserInput) -> CommandHandleOutput:
        command_handle_output = await super().handle(agent_state, user_input)
        command_handle_output.user_msg.removed = True

        provider_options = ['Generate curl command (current LLM config)', 'Export OpenAI API schema JSON', 'Export Anthropic API schema JSON']
        selected_idx = await user_select(provider_options, 'Select export format:')

        if selected_idx is not None:
            export_mode = selected_idx  # 0: curl, 1: openai, 2: anthropic

            if export_mode == 0:
                # Generate curl command with current LLM config
                await self._generate_curl_command(agent_state, command_handle_output)
            else:
                # Export schema JSON (1: openai, 2: anthropic)
                provider = 'openai' if export_mode == 1 else 'anthropic'
                await self._export_schema_json(agent_state, command_handle_output, provider)

        return command_handle_output

    async def _generate_curl_command(self, agent_state: 'AgentState', command_handle_output: CommandHandleOutput):
        """Generate curl command with current LLM configuration"""
        # Get current LLM config
        config = agent_state.config
        if not config:
            command_handle_output.user_msg.set_extra_data('debug_error', 'No LLM configuration found')
            return

        # Determine provider based on base_url or model
        base_url = config.base_url.value if config.base_url else None
        model_name = config.model_name.value if config.model_name else None
        api_key = config.api_key.value if config.api_key else None

        if not api_key:
            command_handle_output.user_msg.set_extra_data('debug_error', 'No API key found in configuration')
            return

        # Detect provider
        is_anthropic = base_url and 'anthropic' in base_url

        # Get messages in appropriate format
        messages = []
        system_messages = []
        role_counts = Counter()
        for msg in agent_state.session.messages.messages:
            if not msg.removed and bool(msg):
                role_counts[msg.role] += 1

        if is_anthropic:
            # Use the convert_to_anthropic method to properly separate system messages
            all_messages = [msg for msg in agent_state.session.messages.messages if not msg.removed and bool(msg)]
            system_messages, messages = AnthropicProxy.convert_to_anthropic(all_messages)
        else:
            for msg in agent_state.session.messages.messages:
                if not msg.removed and bool(msg):
                    messages.append(msg.to_openai())

        # Get tools in appropriate format
        tools = []
        for tool in agent_state.all_tools:
            if is_anthropic:
                tools.append(tool.anthropic_schema())
            else:
                tools.append(tool.openai_schema())

        # Generate curl command
        curl_command = self._build_curl_command(base_url, api_key, model_name, messages, tools, is_anthropic, config, system_messages if is_anthropic else None)

        # Save curl command to file
        debug_dir = agent_state.session.work_dir / '.klaude' / 'debug'
        debug_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        provider_name = 'anthropic' if is_anthropic else 'openai'
        filename = f'debug_curl_{provider_name}_{timestamp}.sh'
        debug_file = debug_dir / filename
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write('#!/bin/bash\n\n')
            f.write('# Generated curl command for current LLM configuration\n')
            f.write(f'# Provider: {provider_name.upper()}\n')
            f.write(f'# Model: {model_name}\n\n')
            f.write(curl_command)

        # Make file executable
        debug_file.chmod(0o755)
        command_handle_output.user_msg.set_extra_data(
            'debug_exported',
            {'type': 'curl', 'provider': provider_name, 'file_path': str(debug_file), 'message_count': len(messages), 'tool_count': len(tools), 'role_counts': dict(role_counts)},
        )

    async def _export_schema_json(self, agent_state: 'AgentState', command_handle_output: CommandHandleOutput, provider: str):
        """Export schema JSON for specified provider"""
        # Get messages and tools in the selected format
        messages = []
        tools = []
        role_counts = Counter()
        system_messages = []

        if provider == 'anthropic':
            # Use the convert_to_anthropic method to properly separate system messages
            all_messages = [msg for msg in agent_state.session.messages.messages if not msg.removed and bool(msg)]
            system_messages, messages = AnthropicProxy.convert_to_anthropic(all_messages)

            # Count roles from the original messages
            for msg in all_messages:
                role_counts[msg.role] += 1
        else:  # openai
            for msg in agent_state.session.messages.messages:
                if not msg.removed and bool(msg):
                    role_counts[msg.role] += 1
                    messages.append(msg.to_openai())

        for tool in agent_state.all_tools:
            if provider == 'openai':
                tools.append(tool.openai_schema())
            else:  # anthropic
                tools.append(tool.anthropic_schema())

        # Create debug data
        if provider == 'anthropic':
            debug_data = {'messages': messages, 'tools': tools}
            if system_messages:
                debug_data['system'] = system_messages
        else:
            debug_data = {'messages': messages, 'tools': tools}

        # Create .klaude/debug directory in session work directory
        debug_dir = agent_state.session.work_dir / '.klaude' / 'debug'
        debug_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = int(time.time())
        filename = f'debug_{provider}_{timestamp}.json'
        debug_file = debug_dir / filename

        # Save to file
        with open(debug_file, 'w', encoding='utf-8') as f:
            json.dump(debug_data, f, indent=2, ensure_ascii=False)

        # Auto-open the file
        try:
            subprocess.run(['open', str(debug_file)], check=False)
        except Exception:
            pass

        command_handle_output.user_msg.set_extra_data(
            'debug_exported',
            {'type': 'schema', 'provider': provider, 'file_path': str(debug_file), 'message_count': len(messages), 'tool_count': len(tools), 'role_counts': dict(role_counts)},
        )

    def _build_curl_command(self, base_url: str, api_key: str, model_name: str, messages: list, tools: list, is_anthropic: bool, config, system_messages: list = None) -> str:
        """Build curl command string"""
        if is_anthropic:
            return self._build_anthropic_curl(base_url, api_key, model_name, messages, tools, config, system_messages)
        else:
            return self._build_openai_curl(base_url, api_key, model_name, messages, tools, config)

    def _build_anthropic_curl(self, base_url: str, api_key: str, model_name: str, messages: list, tools: list, config, system_messages: list = None) -> str:
        """Build Anthropic curl command"""
        url = f'{base_url.rstrip("/")}/messages'
        max_tokens = config.max_tokens.value if config.max_tokens else 32000

        payload = {'model': model_name, 'max_tokens': max_tokens, 'messages': messages}

        if system_messages:
            payload['system'] = system_messages

        if tools:
            payload['tools'] = tools

        payload_json = json.dumps(payload, indent=2, ensure_ascii=False)

        # Use heredoc to avoid escaping issues
        curl_cmd = f'''curl -X POST "{url}" \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: {api_key}" \\
  -H "anthropic-version: 2023-06-01" \\
  -d @- << 'EOF'
{payload_json}
EOF'''

        return curl_cmd

    def _build_openai_curl(self, base_url: str, api_key: str, model_name: str, messages: list, tools: list, config) -> str:
        """Build OpenAI curl command"""
        url = f'{base_url.rstrip("/")}/chat/completions?ak={api_key}'
        max_tokens = config.max_tokens.value if config.max_tokens else 32000

        payload = {'model': model_name, 'max_tokens': max_tokens, 'messages': messages}

        if tools:
            payload['tools'] = tools

        payload_json = json.dumps(payload, indent=2, ensure_ascii=False)

        # Use heredoc to avoid escaping issues
        curl_cmd = f'''curl -X POST "{url}" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer {api_key}" \\
  -d @- << 'EOF'
{payload_json}
EOF'''

        return curl_cmd

    def render_user_msg_suffix(self, user_msg: UserMessage) -> Generator[RichRenderable, None, None]:
        debug_info = user_msg.get_extra_data('debug_exported')
        debug_error = user_msg.get_extra_data('debug_error')
        if debug_error:
            yield render_suffix(Text(f'Error: {debug_error}', style='red'))
            return

        if debug_info:
            export_type = debug_info.get('type', 'schema')
            provider = debug_info['provider']
            file_path = debug_info['file_path']

            if export_type == 'curl':
                # Curl command export
                first_line = Text.assemble(
                    ('✔ ', ColorStyle.SUCCESS.bold),
                    f'{provider.upper()} curl command generated: ',
                    (file_path, ColorStyle.MAIN.bold),
                )

                # Second line: statistics with bold numbers
                role_counts = debug_info['role_counts']
                total_messages = debug_info['message_count']
                tool_count = debug_info['tool_count']

                # Build role statistics text
                role_parts = []
                for role, count in role_counts.items():
                    role_parts.extend([role, ': ', (str(count), ColorStyle.MAIN.bold), ', '])

                # Remove the last comma and space
                if role_parts:
                    role_parts = role_parts[:-1]

                second_line = Text.assemble(
                    (str(tool_count), ColorStyle.MAIN.bold), ' tools, ', (str(total_messages), ColorStyle.MAIN.bold), ' messages (', *role_parts, ') - executable curl script'
                )

                # Third line: curl usage tip
                third_line = Text('Tip: Direct curl may return end_turn - consider remove some messages for continuation', style=ColorStyle.HINT)

                yield render_suffix(Group(first_line, second_line, third_line))
            else:
                # Schema JSON export
                first_line = Text.assemble(
                    f'{provider.upper()} native API schema exported to ',
                    (file_path, ColorStyle.MAIN.bold),
                )

                # Second line: statistics with bold numbers
                role_counts = debug_info['role_counts']
                total_messages = debug_info['message_count']
                tool_count = debug_info['tool_count']

                # Build role statistics text
                role_parts = []
                for role, count in role_counts.items():
                    role_parts.extend([role, ': ', (str(count), ColorStyle.MAIN.bold), ', '])

                # Remove the last comma and space
                if role_parts:
                    role_parts = role_parts[:-1]

                second_line = Text.assemble(
                    (str(tool_count), ColorStyle.MAIN.bold), ' tools, ', (str(total_messages), ColorStyle.MAIN.bold), ' messages (', *role_parts, ') - ready for direct API usage'
                )

                yield render_suffix(Group(first_line, second_line))
