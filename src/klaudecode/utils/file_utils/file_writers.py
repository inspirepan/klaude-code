from .file_validation import ensure_directory_exists


def write_file_content(file_path: str, content: str, encoding: str = 'utf-8') -> str:
    """Write content to file, creating parent directories if needed.

    Args:
        file_path: Path to write to
        content: Content to write
        encoding: Encoding to use

    Returns:
        Error message if write fails, empty string on success
    """
    try:
        ensure_directory_exists(file_path)
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        return ''
    except Exception as e:
        return f'Failed to write file: {str(e)}'
