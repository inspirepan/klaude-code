import re

import fnmatch
from pathlib import Path
from typing import List, Optional


def _parse_gitignore(gitignore_path: Path) -> List[str]:
    """解析.gitignore文件，返回忽略模式列表"""
    patterns = []
    if not gitignore_path.exists():
        return patterns

    try:
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    patterns.append(line)
    except Exception:
        pass

    return patterns


def _should_ignore(path: Path, ignore_patterns: List[str], base_path: Path) -> bool:
    """检查路径是否应该被忽略"""
    if not ignore_patterns:
        return False

    relative_path = path.relative_to(base_path)
    path_str = str(relative_path)

    for pattern in ignore_patterns:
        # 简单的模式匹配实现
        if pattern.endswith('/'):
            # 目录匹配
            pattern_name = pattern[:-1]
            if path.is_dir() and (path_str == pattern_name or path_str.startswith(pattern) or path.name == pattern_name):
                return True
        elif '*' in pattern:
            # 通配符匹配
            if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True
        else:
            # 精确匹配
            if path_str == pattern or path.name == pattern:
                return True

    return False


def _build_tree(path: Path, ignore_patterns: List[str], base_path: Path, indent: int = 0) -> List[str]:
    """递归构建目录树"""
    result = []

    if _should_ignore(path, ignore_patterns, base_path):
        return result

    # 添加当前项目
    prefix = '  ' * indent
    if path.is_dir():
        result.append(f'{prefix}- {path.name}/')

        # 获取子项目并排序
        try:
            children = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            for child in children:
                if not _should_ignore(child, ignore_patterns, base_path):
                    result.extend(_build_tree(child, ignore_patterns, base_path, indent + 1))
        except PermissionError:
            pass
    else:
        result.append(f'{prefix}- {path.name}')

    return result


def get_directory_structure(path: str, ignore_pattern: Optional[List[str]] = None, max_chars: int = 40000, max_lines: int = 0) -> tuple[str, str]:
    """
    获取目录结构，支持字符数和行数限制，返回完整结果和截断的human-friendly结果

    Args:
        path: 目录路径
        ignore_pattern: 额外的忽略模式列表（可选）
        max_chars: 最大字符数限制，0表示无限制
        max_lines: 最大行数限制，0表示无限制

    Returns:
        tuple[str, str]: (完整结果, human-friendly截断结果)
    """
    path_obj = Path(path).resolve()

    if not path_obj.exists():
        return f'- {path} (路径不存在)'

    # 读取.gitignore文件
    gitignore_path = path_obj / '.gitignore'
    ignore_patterns = _parse_gitignore(gitignore_path)

    # 添加默认忽略模式（Git相关）
    default_ignores = ['.git/', '.gitignore']
    ignore_patterns.extend(default_ignores)

    # 添加额外的忽略模式
    if ignore_pattern:
        ignore_patterns.extend(ignore_pattern)

    # 构建文件树
    result = [f'- {path_obj.name}/']

    # 获取子项目并排序
    try:
        children = sorted(path_obj.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        for child in children:
            if not _should_ignore(child, ignore_patterns, path_obj):
                result.extend(_build_tree(child, ignore_patterns, path_obj, 1))
    except PermissionError:
        result.append('  - (权限不足)')

    full_content = '\n'.join(result)
    lines = full_content.split('\n')

    # 创建human-friendly截断版本（行数限制为20行）
    human_line_limit = 20
    if max_lines > 0:
        human_line_limit = min(max_lines, human_line_limit)

    if len(lines) > human_line_limit + 5:  # 如果超过限制+缓冲
        human_result = '\n'.join(lines[:human_line_limit])
        remaining_lines = len(lines) - human_line_limit
        human_result += f'\n... + {remaining_lines} lines'
    else:
        human_result = full_content

    # 如果没有字符限制或内容未超过限制，返回完整内容
    if max_chars <= 0 or len(full_content) <= max_chars:
        return full_content, human_result

    # 智能截断：不在项目中间截断
    truncated_lines = []
    current_length = 0

    for line in lines:
        if current_length + len(line) + 1 > max_chars:  # +1 for newline
            break
        truncated_lines.append(line)
        current_length += len(line) + 1

    truncated_content = '\n'.join(truncated_lines)
    truncated_content += f'\n... (truncated at {max_chars} characters, use LS tool with specific paths to explore more)'

    # 更新human_result如果字符截断比行截断更严格
    if len(truncated_content) < len(human_result):
        human_result = truncated_content

    return truncated_content, human_result


def truncate_end_text(text: str, max_lines: int = 15) -> str:
    lines = text.splitlines()

    if len(lines) <= max_lines + 5:
        return text

    truncated_lines = lines[:max_lines]
    remaining_lines = len(lines) - max_lines
    truncated_content = '\n'.join(truncated_lines)
    truncated_content += f'\n... + {remaining_lines} lines'
    return truncated_content


def sanitize_filename(text: str, max_length: int = 20) -> str:
    if not text:
        return 'untitled'
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    if not text:
        return 'untitled'
    if len(text) > max_length:
        text = text[:max_length].rstrip()

    return text
