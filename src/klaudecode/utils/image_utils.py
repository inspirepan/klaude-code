import base64
import mimetypes
from pathlib import Path

from ..message import Attachment

READ_MAX_IMAGE_SIZE_KB = 2048
READ_IMAGE_SIZE_LIMIT_ERROR_MSG = 'Image ({size:.1f}KB) exceeds maximum allowed size ({max_size}KB).'


class ImageReadResult(Attachment):
    success: bool = True
    error_msg: str = ''


def read_image_as_base64(file_path: str) -> tuple[str, str]:
    """Read an image file and return base64 encoded content and media type."""
    try:
        with open(file_path, 'rb') as f:
            image_data = f.read()

        # Get media type
        media_type, _ = mimetypes.guess_type(file_path)
        if not media_type:
            # Default media types for common image formats
            suffix = Path(file_path).suffix.lower()
            media_type_map = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.bmp': 'image/bmp',
                '.webp': 'image/webp',
                '.svg': 'image/svg+xml',
            }
            media_type = media_type_map.get(suffix, 'image/png')

        # Encode to base64
        base64_content = base64.b64encode(image_data).decode('utf-8')
        return base64_content, media_type
    except Exception as e:
        raise IOError(f'Failed to read image file: {str(e)}')


def execute_read_image(file_path: str) -> ImageReadResult:
    result = ImageReadResult(type='image', path=file_path)
    try:
        # Check file size limit
        file_size = Path(file_path).stat().st_size
        max_size_bytes = READ_MAX_IMAGE_SIZE_KB * 1024
        if file_size > max_size_bytes:
            result.success = False
            size_kb = file_size / 1024
            result.error_msg = READ_IMAGE_SIZE_LIMIT_ERROR_MSG.format(size=size_kb, max_size=READ_MAX_IMAGE_SIZE_KB)
            return result

        # Read image as base64
        base64_content, media_type = read_image_as_base64(file_path)

        # Set result for image
        result.content = base64_content
        result.media_type = media_type

        # Convert to appropriate unit
        if file_size < 1024:
            result.size_str = f'{file_size}B'
        elif file_size < 1024 * 1024:
            result.size_str = f'{file_size / 1024:.1f}KB'
        else:
            result.size_str = f'{file_size / (1024 * 1024):.1f}MB'
        return result

    except Exception as e:
        result.success = False
        result.error_msg = str(e)
        return result
