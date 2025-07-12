from pathlib import Path


def get_relative_path_for_display(file_path: str) -> str:
    """Convert absolute path to relative path for display purposes.

    Args:
        file_path: Absolute file path to convert

    Returns:
        Relative path if shorter than absolute path, otherwise absolute path
    """
    try:
        abs_path = Path(file_path).resolve()
        relative_path = abs_path.relative_to(Path.cwd())
        relative_str = str(relative_path)
        return relative_str if len(relative_str) < len(file_path) else file_path
    except (ValueError, OSError):
        return file_path
