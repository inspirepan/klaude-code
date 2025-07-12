from typing import Optional, Tuple


def read_file_content(file_path: str, encoding: str = 'utf-8') -> Tuple[str, str]:
    """Read file content with fallback encoding handling.

    Args:
        file_path: Path to file to read
        encoding: Primary encoding to try

    Returns:
        Tuple of (content, warning_message)
    """
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            content = f.read()
        return content, ''
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                content = f.read()
            return content, '<system-reminder>warning: File decoded using latin-1 encoding</system-reminder>'
        except Exception as e:
            return '', f'Failed to read file: {str(e)}'
    except Exception as e:
        return '', f'Failed to read file: {str(e)}'


def read_file_lines_partial(file_path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> tuple[list[str], str]:
    """Read file lines with offset and limit to avoid loading entire file into memory"""
    try:
        lines = []
        with open(file_path, 'r', encoding='utf-8') as f:
            if offset is not None and offset > 1:
                for _ in range(offset - 1):
                    try:
                        next(f)
                    except StopIteration:
                        break

            count = 0
            max_lines = limit if limit is not None else float('inf')

            for line in f:
                if count >= max_lines:
                    break
                lines.append(line.rstrip('\n\r'))
                count += 1

        return lines, ''
    except UnicodeDecodeError:
        try:
            lines = []
            with open(file_path, 'r', encoding='latin-1') as f:
                if offset is not None and offset > 1:
                    for _ in range(offset - 1):
                        try:
                            next(f)
                        except StopIteration:
                            break

                count = 0
                max_lines = limit if limit is not None else float('inf')

                for line in f:
                    if count >= max_lines:
                        break
                    lines.append(line.rstrip('\n\r'))
                    count += 1

            return lines, '<system-reminder>warning: File decoded using latin-1 encoding</system-reminder>'
        except Exception as e:
            return [], f'Failed to read file: {str(e)}'
    except Exception as e:
        return [], f'Failed to read file: {str(e)}'
