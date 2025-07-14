import re
from pathlib import Path
from typing import TYPE_CHECKING, List, Tuple

from ..message import Attachment, UserMessage
from ..prompt.reminder import LANGUAGE_REMINDER
from ..prompt.tools import LS_TOOL_RESULT_REMINDER
from ..tools.read import execute_read
from ..tui import console

if TYPE_CHECKING:
    from ..agent import AgentState
from ..utils.file_utils import get_directory_structure
from .input_command import _SLASH_COMMANDS, UserInput
from .input_mode import _INPUT_MODES, NORMAL_MODE_NAME, NormalMode


class UserInputHandler:
    def __init__(self, agent_state: 'AgentState', input_session=None):
        self.agent_state = agent_state
        self.input_session = input_session

    def _parse_image_refs(self, text: str) -> List[Attachment]:
        """Parse [Image #N] patterns and return image attachments from paste dict."""
        attachments = []
        if not self.input_session:
            return attachments

        pattern = r'\[Image #(\d+)\]'  # Match [Image #N] pattern
        matches = list(re.finditer(pattern, text))

        for match in matches:
            image_id = match.group(1)
            if image_id in self.input_session.paste_dict:
                paste_item = self.input_session.paste_dict[image_id]

                if paste_item.type == 'file':
                    # Handle file-based image
                    result = execute_read(paste_item.path, tracker=self.agent_state.session.file_tracker)
                    if result.success:
                        attachments.append(result)
                elif paste_item.type == 'clipboard':
                    # Handle clipboard-based image (base64)
                    try:
                        # Create an attachment for clipboard image with base64 content
                        attachment = Attachment(
                            type='image',
                            path=f'Image #{image_id}',
                            content=paste_item.content,  # Store as base64
                            media_type='image/png',
                        )
                        attachments.append(attachment)
                    except Exception:
                        continue

        return attachments

    def _parse_at_files(self, text: str) -> List[Attachment]:
        """Parse @filepath patterns and return file attachments."""
        attachments = []
        pattern = r'@([^\s]+)'  # Match @ followed by non-whitespace characters

        # Find all matches first
        matches = list(re.finditer(pattern, text))

        for match in matches:
            file_path = match.group(1)

            # Try to resolve the file path
            abs_path = None
            if file_path.startswith('/'):
                # Absolute path
                abs_path = file_path
            else:
                # Relative path - try to resolve from current directory
                try:
                    abs_path = str(Path.cwd() / file_path)
                except Exception:
                    # If resolution fails, skip this @file reference
                    continue

            if not Path(abs_path).exists():
                continue

            # Check if it's a directory (ends with / or is an existing directory)
            is_directory = file_path.endswith('/') or Path(abs_path).is_dir()

            if is_directory:
                # Handle directory
                try:
                    dir_result, _, _ = get_directory_structure(abs_path, None, max_chars=40000, show_hidden=False)
                    if dir_result:
                        # Add LS_TOOL_RESULT_REMINDER like the LS tool does
                        content = dir_result + '\n\n' + LS_TOOL_RESULT_REMINDER
                        attachments.append(Attachment(type='directory', path=abs_path, content=content))
                except Exception:
                    continue
            else:
                # Handle file
                result = execute_read(abs_path, tracker=self.agent_state.session.file_tracker)
                if result.success:
                    attachments.append(result)
        return attachments

    async def handle(self, user_input_text: str, print_msg: bool = True) -> bool:
        # Parse [Image #N] references first
        image_attachments = self._parse_image_refs(user_input_text)

        # Parse @file references
        file_attachments = self._parse_at_files(user_input_text)

        # Combine all attachments
        attachments = image_attachments + file_attachments

        command_name, cleaned_input = self._parse_command(user_input_text)
        command = _INPUT_MODES.get(command_name, _SLASH_COMMANDS.get(command_name, NormalMode()))
        command_handle_output = await command.handle(
            self.agent_state,
            UserInput(
                command_name=command_name or NORMAL_MODE_NAME,
                cleaned_input=cleaned_input,
                raw_input=user_input_text,
            ),
        )
        user_msg = command_handle_output.user_msg
        if user_msg is not None and user_msg.is_valid():
            # Add attachments to the user message
            if attachments:
                user_msg.attachments = attachments

            # self._handle_language_reminder(user_msg)
            self.agent_state.session.append_message(user_msg)
            if print_msg:
                console.print(user_msg)
            elif command_handle_output.need_render_suffix:
                for item in user_msg.get_suffix_renderable():
                    console.print(item)

        return command_handle_output.need_agent_run

    def _parse_command(self, text: str) -> Tuple[str, str]:
        if not text.strip():
            return '', text

        stripped = text.strip()
        if stripped.startswith('/'):
            parts = stripped[1:].split(None, 1)
            if parts:
                command_part = parts[0]
                remaining_text = parts[1] if len(parts) > 1 else ''
                if command_part in _SLASH_COMMANDS:
                    return command_part, remaining_text
                if command_part in _INPUT_MODES:
                    return command_part, remaining_text
        return '', text

    def _handle_language_reminder(self, user_msg: UserMessage):
        if len(self.agent_state.session.messages) > 2:
            return
        user_msg.append_post_system_reminder(LANGUAGE_REMINDER)
