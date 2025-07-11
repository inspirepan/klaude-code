from typing import TYPE_CHECKING, Callable

from rich.abc import RichRenderable

if TYPE_CHECKING:
    from .tool_call import ToolCall
    from .tool_result import ToolMessage
    from .user import UserMessage

_TOOL_CALL_RENDERERS = {}
_TOOL_RESULT_RENDERERS = {}
_USER_MSG_RENDERERS = {}
_USER_MSG_SUFFIX_RENDERERS = {}
_USER_MSG_CONTENT_FUNCS = {}


def register_tool_call_renderer(tool_name: str, renderer_func: Callable[['ToolCall', bool], RichRenderable] = None):
    """Register a tool call renderer function or use as decorator"""
    if renderer_func is None:
        # Used as decorator
        def decorator(func: Callable[['ToolCall', bool], RichRenderable]):
            _TOOL_CALL_RENDERERS[tool_name] = func
            return func

        return decorator
    else:
        # Used as function
        _TOOL_CALL_RENDERERS[tool_name] = renderer_func


def register_tool_result_renderer(tool_name: str, renderer_func: Callable[['ToolMessage'], RichRenderable] = None):
    """Register a tool result renderer function or use as decorator"""
    if renderer_func is None:
        # Used as decorator
        def decorator(func: Callable[['ToolMessage'], RichRenderable]):
            _TOOL_RESULT_RENDERERS[tool_name] = func
            return func

        return decorator
    else:
        # Used as function
        _TOOL_RESULT_RENDERERS[tool_name] = renderer_func


def register_user_msg_suffix_renderer(user_msg_type: str, renderer_func: Callable[['UserMessage'], RichRenderable] = None):
    """Register a user message suffix renderer function or use as decorator"""
    if renderer_func is None:
        # Used as decorator
        def decorator(func: Callable[['UserMessage'], RichRenderable]):
            _USER_MSG_SUFFIX_RENDERERS[user_msg_type] = func
            return func

        return decorator
    else:
        # Used as function
        _USER_MSG_SUFFIX_RENDERERS[user_msg_type] = renderer_func


def register_user_msg_renderer(user_msg_type: str, renderer_func: Callable[['UserMessage'], RichRenderable] = None):
    """Register a user message renderer function or use as decorator"""
    if renderer_func is None:
        # Used as decorator
        def decorator(func: Callable[['UserMessage'], RichRenderable]):
            _USER_MSG_RENDERERS[user_msg_type] = func
            return func

        return decorator
    else:
        # Used as function
        _USER_MSG_RENDERERS[user_msg_type] = renderer_func


def register_user_msg_content_func(user_msg_type: str, content_func: Callable[['UserMessage'], str] = None):
    """Register a user message content function or use as decorator"""
    if content_func is None:
        # Used as decorator
        def decorator(func: Callable[['UserMessage'], str]):
            _USER_MSG_CONTENT_FUNCS[user_msg_type] = func
            return func

        return decorator
    else:
        # Used as function
        _USER_MSG_CONTENT_FUNCS[user_msg_type] = content_func
