import os
from typing import Annotated

from pydantic import BaseModel, Field
from rich.text import Text

from ..message import ToolCall, register_tool_call_renderer
from ..tool import Tool, ToolInstance
from .file_utils import cache_file_content, cleanup_backup, create_backup, ensure_directory_exists, restore_backup, validate_file_cache, write_file_content

"""
- Safety mechanism requiring existing files to be read first
- Automatic directory creation and backup recovery
- File permission preservation and encoding handling
"""


class WriteTool(Tool):
    name = 'Write'
    desc = 'Write content to a file (overwrites existing files)'

    class Input(BaseModel):
        file_path: Annotated[str, Field(description='The absolute path to the file to write')]
        content: Annotated[str, Field(description='The content to write to the file')]

        def __str__(self):
            return f'Writing to {self.file_path} ({len(self.content)} characters)'

    @classmethod
    def invoke(cls, tool_call: ToolCall, instance: 'ToolInstance'):
        args: 'WriteTool.Input' = cls.parse_input_args(tool_call)

        file_exists = os.path.exists(args.file_path)
        backup_path = None

        try:
            # If file exists, it must have been read first (safety check)
            if file_exists:
                is_valid, error_msg = validate_file_cache(args.file_path)
                if not is_valid:
                    instance.tool_result().set_error_msg(error_msg)
                    return

                # Create backup before writing
                backup_path = create_backup(args.file_path)

            else:
                # For new files, ensure directory exists
                ensure_directory_exists(args.file_path)

            # Write the content
            error_msg = write_file_content(args.file_path, args.content)
            if error_msg:
                # Restore from backup if write failed
                if backup_path:
                    try:
                        restore_backup(args.file_path, backup_path)
                        backup_path = None  # Don't cleanup since we restored
                    except Exception:
                        pass
                instance.tool_result().set_error_msg(error_msg)
                return

            # Update cache with new content
            cache_file_content(args.file_path, args.content)

            if file_exists:
                result = f'File updated successfully at: {args.file_path}\n'
            else:
                result = f'File created successfully at: {args.file_path}\n'

            instance.tool_result().set_content(result)

            # Clean up backup on success
            if backup_path:
                cleanup_backup(backup_path)

        except Exception as e:
            # Restore from backup if something went wrong
            if backup_path:
                try:
                    restore_backup(args.file_path, backup_path)
                except Exception:
                    pass

            instance.tool_result().set_error_msg(f'Failed to write file: {str(e)}')


def render_write_args(tool_call: ToolCall):
    file_path = tool_call.tool_args_dict.get('file_path', '')

    tool_call_msg = Text.assemble(
        (tool_call.tool_name, 'bold'),
        '(',
        file_path,
        ')',
    )
    yield tool_call_msg


register_tool_call_renderer('Write', render_write_args)
