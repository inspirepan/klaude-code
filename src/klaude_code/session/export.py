"""Session export functionality for generating HTML transcripts."""

from __future__ import annotations

import html
import importlib.resources
import json
import re
from datetime import datetime
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any, Final, cast

from klaude_code.core.sub_agent import is_sub_agent_tool
from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import (
    AssistantMessageItem,
    ConversationItem,
    DeveloperMessageItem,
    ReasoningEncryptedItem,
    ReasoningTextItem,
    ToolCallItem,
    ToolResultItem,
    ToolResultUIExtra,
    ToolResultUIExtraType,
    UserMessageItem,
)

if TYPE_CHECKING:
    from klaude_code.session.session import Session

COLORS: Final[dict[str, str]] = {
    "bodyBg": "#09090b",  # Zinc 950
    "containerBg": "#18181b",  # Zinc 900
    "cardBg": "#27272a",  # Zinc 800
    "borderColor": "#3f3f46",  # Zinc 700
    "userMessageBg": "#27272a",  # Zinc 800
    "toolPendingBg": "#2a2a35",
    "toolSuccessBg": "#1c2e26",
    "toolErrorBg": "#2e1c1c",
    "text": "#f4f4f5",  # Zinc 100
    "textDim": "#a1a1aa",  # Zinc 400
    "cyan": "#22d3ee",  # Cyan 400
    "green": "#4ade80",  # Green 400
    "red": "#f87171",  # Red 400
    "yellow": "#facc15",  # Yellow 400
    "blue": "#60a5fa",  # Blue 400
    "italic": "#a1a1aa",
}

_TOOL_OUTPUT_PREVIEW_LINES: Final[int] = 12
_MAX_FILENAME_MESSAGE_LEN: Final[int] = 50


def _sanitize_filename(text: str) -> str:
    """Sanitize text for use in filename."""
    sanitized = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", text)
    sanitized = re.sub(r"\s+", "_", sanitized.strip())
    return sanitized[:_MAX_FILENAME_MESSAGE_LEN] if sanitized else "export"


def _escape_html(text: str) -> str:
    return html.escape(text, quote=True).replace("'", "&#39;")


def _shorten_path(path: str) -> str:
    home = str(Path.home())
    if path.startswith(home):
        return path.replace(home, "~", 1)
    return path


def _format_timestamp(value: float | None) -> str:
    if not value or value <= 0:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def get_first_user_message(history: list[ConversationItem]) -> str:
    """Extract the first user message content from conversation history."""
    for item in history:
        if isinstance(item, UserMessageItem) and item.content:
            content = item.content.strip()
            first_line = content.split("\n")[0]
            return first_line[:100] if len(first_line) > 100 else first_line
    return "export"


def get_default_export_path(session: Session) -> Path:
    """Get default export path for a session."""
    from klaude_code.session.session import Session as SessionClass

    exports_dir = SessionClass._exports_dir()  # pyright: ignore[reportPrivateUsage]
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    first_msg = get_first_user_message(session.conversation_history)
    sanitized_msg = _sanitize_filename(first_msg)
    filename = f"{timestamp}_{sanitized_msg}.html"
    return exports_dir / filename


def _load_template() -> str:
    """Load the HTML template from the templates directory."""
    template_file = importlib.resources.files("klaude_code.session.templates").joinpath("export_session.html")
    return template_file.read_text(encoding="utf-8")


def _build_tools_html(tools: list[ToolSchema]) -> str:
    if not tools:
        return '<div style="padding: 12px; font-style: italic;">No tools registered for this session.</div>'
    chunks: list[str] = []
    for tool in tools:
        name = _escape_html(tool.name)
        description = _escape_html(tool.description)
        params_html = _build_tool_params_html(tool.parameters)
        chunks.append(
            f'<details class="tool-details">'
            f"<summary>{name}</summary>"
            f'<div class="details-content">'
            f'<div class="tool-description">{description}</div>'
            f"{params_html}"
            f"</div>"
            f"</details>"
        )
    return "".join(chunks)


def _build_tool_params_html(parameters: dict[str, object]) -> str:
    if not parameters:
        return ""
    properties = parameters.get("properties")
    if not properties or not isinstance(properties, dict):
        return ""
    required_list = cast(list[str], parameters.get("required", []))
    required_params: set[str] = set(required_list)

    params_items: list[str] = []
    typed_properties = cast(dict[str, dict[str, Any]], properties)
    for param_name, param_schema in typed_properties.items():
        escaped_name = _escape_html(param_name)
        param_type_raw = param_schema.get("type", "any")
        if isinstance(param_type_raw, list):
            type_list = cast(list[str], param_type_raw)
            param_type = " | ".join(type_list)
        else:
            param_type = str(param_type_raw)
        escaped_type = _escape_html(param_type)
        param_desc_raw = param_schema.get("description", "")
        escaped_desc = _escape_html(str(param_desc_raw))

        required_badge = ""
        if param_name in required_params:
            required_badge = '<span class="tool-param-required">(required)</span>'

        desc_html = ""
        if escaped_desc:
            desc_html = f'<div class="tool-param-desc">{escaped_desc}</div>'

        params_items.append(
            f'<div class="tool-param">'
            f'<span class="tool-param-name">{escaped_name}</span> '
            f'<span class="tool-param-type">[{escaped_type}]</span>'
            f"{required_badge}"
            f"{desc_html}"
            f"</div>"
        )

    if not params_items:
        return ""

    return f'<div class="tool-params"><div class="tool-params-title">Parameters:</div>{"".join(params_items)}</div>'


def _render_assistant_message(index: int, content: str) -> str:
    encoded = _escape_html(content)
    return (
        f'<div class="message-group assistant-message-group">'
        f'<div class="message-header">'
        f'<div class="role-label assistant">Assistant</div>'
        f'<div class="assistant-toolbar">'
        f'<button type="button" class="raw-toggle" aria-pressed="false" title="Toggle raw text view">Raw</button>'
        f'<button type="button" class="copy-raw-btn" title="Copy raw content">Copy</button>'
        f"</div>"
        f"</div>"
        f'<div class="message-content assistant-message">'
        f'<div class="assistant-rendered markdown-content markdown-body" data-raw="{encoded}">'
        f'<noscript><pre style="white-space: pre-wrap;">{encoded}</pre></noscript>'
        f"</div>"
        f'<pre class="assistant-raw">{encoded}</pre>'
        f"</div>"
        f"</div>"
    )


def _try_render_todo_args(arguments: str) -> str | None:
    try:
        parsed = json.loads(arguments)
        if not isinstance(parsed, dict) or "todos" not in parsed or not isinstance(parsed["todos"], list):
            return None

        todos = cast(list[dict[str, str]], parsed["todos"])
        if not todos:
            return None

        items_html: list[str] = []
        for todo in todos:
            content = _escape_html(todo.get("content", ""))
            status = todo.get("status", "pending")
            status_class = f"status-{status}"

            items_html.append(
                f'<div class="todo-item {status_class}">'
                f'<span class="todo-bullet">●</span>'
                f'<span class="todo-content">{content}</span>'
                f"</div>"
            )

        if not items_html:
            return None

        return f'<div class="todo-list">{"".join(items_html)}</div>'
    except Exception:
        return None


def _render_sub_agent_result(content: str) -> str:
    encoded = _escape_html(content)
    return (
        f'<div class="subagent-result-container">'
        f'<div class="subagent-toolbar">'
        f'<button type="button" class="raw-toggle" aria-pressed="false" title="Toggle raw text view">Raw</button>'
        f'<button type="button" class="copy-raw-btn" title="Copy raw content">Copy</button>'
        f"</div>"
        f'<div class="subagent-content">'
        f'<div class="subagent-rendered markdown-content markdown-body" data-raw="{encoded}">'
        f'<noscript><pre style="white-space: pre-wrap;">{encoded}</pre></noscript>'
        f"</div>"
        f'<pre class="subagent-raw">{encoded}</pre>'
        f"</div>"
        f"</div>"
    )


def _render_text_block(text: str) -> str:
    lines = text.splitlines()
    escaped_lines = [_escape_html(line) for line in lines]

    if len(lines) <= _TOOL_OUTPUT_PREVIEW_LINES:
        content = "\n".join(escaped_lines)
        return f'<div style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 13px;">{content}</div>'

    preview = "\n".join(escaped_lines[:_TOOL_OUTPUT_PREVIEW_LINES])
    full = "\n".join(escaped_lines)

    return (
        f'<div class="expandable-output expandable">'
        f'<div class="preview-text" style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 13px;">{preview}</div>'
        f'<div class="expand-hint expand-text">Click to expand full output ({len(lines)} lines)</div>'
        f'<div class="full-text" style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 13px;">{full}</div>'
        f'<div class="collapse-hint">Click to collapse</div>'
        f"</div>"
    )


def _render_diff_block(diff: str) -> str:
    lines = diff.splitlines()
    rendered: list[str] = []
    for line in lines:
        escaped = _escape_html(line)
        if line.startswith("+"):
            rendered.append(f'<span class="diff-line diff-plus">{escaped}</span>')
        elif line.startswith("-"):
            rendered.append(f'<span class="diff-line diff-minus">{escaped}</span>')
        else:
            rendered.append(f'<span class="diff-line diff-ctx">{escaped}</span>')
    return f'<div class="diff-view">{"".join(rendered)}</div>'


def _get_diff_text(ui_extra: ToolResultUIExtra | None) -> str | None:
    if ui_extra is None:
        return None
    if ui_extra.type != ToolResultUIExtraType.DIFF_TEXT:
        return None
    return ui_extra.diff_text


def _get_mermaid_link_html(ui_extra: ToolResultUIExtra | None, tool_call: ToolCallItem | None = None) -> str | None:
    if ui_extra is None:
        return None
    if ui_extra.type != ToolResultUIExtraType.MERMAID_LINK:
        return None
    if ui_extra.mermaid_link is None or not ui_extra.mermaid_link.link:
        return None
    link = _escape_html(ui_extra.mermaid_link.link)
    lines = ui_extra.mermaid_link.line_count

    copy_btn = ""
    if tool_call and tool_call.name == "Mermaid":
        try:
            args = json.loads(tool_call.arguments)
            code = args.get("code")
            if code:
                escaped_code = _escape_html(code)
                copy_btn = f'<button type="button" class="copy-mermaid-btn" data-code="{escaped_code}" title="Copy Mermaid Code">Copy Code</button>'
        except Exception:
            pass

    return (
        '<div style="display: flex; justify-content: space-between; align-items: center; font-family: var(--font-mono);">'
        f"<span>Lines: {lines}</span>"
        f"<div>"
        f"{copy_btn}"
        f'<a href="{link}" target="_blank" rel="noopener noreferrer" style="color: var(--accent); text-decoration: underline; margin-left: 8px;">View Diagram</a>'
        f"</div>"
        "</div>"
    )


def _format_tool_call(tool_call: ToolCallItem, result: ToolResultItem | None) -> str:
    args_html = None
    if tool_call.name == "TodoWrite":
        args_html = _try_render_todo_args(tool_call.arguments)

    if args_html is None:
        try:
            parsed = json.loads(tool_call.arguments)
            args_text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            args_text = tool_call.arguments

        args_html = _escape_html(args_text or "")

    if not args_html:
        args_html = '<span style="color: var(--text-dim); font-style: italic;">(no arguments)</span>'

    html_parts = [
        '<div class="tool-call">',
        '<div class="tool-header">',
        f'<span class="tool-name">{_escape_html(tool_call.name)}</span>',
        f'<span class="tool-id">{_escape_html(tool_call.call_id)}</span>',
        "</div>",
        f'<div class="tool-args">{args_html}</div>',
    ]

    if result:
        diff_text = _get_diff_text(result.ui_extra)
        mermaid_html = _get_mermaid_link_html(result.ui_extra, tool_call)

        should_hide_text = tool_call.name == "TodoWrite" and result.status != "error"

        if tool_call.name == "Edit" and not diff_text and result.status != "error":
            try:
                args_data = json.loads(tool_call.arguments)
                old_string = args_data.get("old_string", "")
                new_string = args_data.get("new_string", "")
                if old_string == "" and new_string:
                    diff_text = "\n".join(f"+{line}" for line in new_string.splitlines())
            except Exception:
                pass

        items_to_render: list[str] = []

        if result.output and not should_hide_text:
            if is_sub_agent_tool(tool_call.name):
                items_to_render.append(_render_sub_agent_result(result.output))
            else:
                items_to_render.append(_render_text_block(result.output))

        if diff_text:
            items_to_render.append(_render_diff_block(diff_text))

        if mermaid_html:
            items_to_render.append(mermaid_html)

        if not items_to_render and not result.output and not should_hide_text:
            items_to_render.append('<div style="color: var(--text-dim); font-style: italic;">(empty output)</div>')

        if items_to_render:
            status_class = result.status if result.status in ("success", "error") else "success"
            html_parts.append(f'<div class="tool-result {status_class}">')
            html_parts.extend(items_to_render)
            html_parts.append("</div>")
    else:
        html_parts.append('<div class="tool-result pending">Executing...</div>')

    html_parts.append("</div>")
    return "".join(html_parts)


def _build_messages_html(
    history: list[ConversationItem],
    tool_results: dict[str, ToolResultItem],
) -> str:
    blocks: list[str] = []
    assistant_counter = 0

    renderable_items = [item for item in history if not isinstance(item, (ToolResultItem, ReasoningEncryptedItem))]

    for i, item in enumerate(renderable_items):
        if isinstance(item, UserMessageItem):
            text = _escape_html(item.content or "")
            blocks.append(
                f'<div class="message-group">'
                f'<div class="role-label user">User</div>'
                f'<div class="message-content user" style="white-space: pre-wrap;">{text}</div>'
                f"</div>"
            )
        elif isinstance(item, ReasoningTextItem):
            text = _escape_html(item.content.strip())
            blocks.append(f'<div class="thinking-block">{text.replace(chr(10), "<br>")}</div>')
        elif isinstance(item, AssistantMessageItem):
            assistant_counter += 1
            blocks.append(_render_assistant_message(assistant_counter, item.content or ""))
        elif isinstance(item, DeveloperMessageItem):
            content = _escape_html(item.content or "")

            next_item = renderable_items[i + 1] if i + 1 < len(renderable_items) else None
            extra_class = ""
            if isinstance(next_item, (UserMessageItem, AssistantMessageItem)):
                extra_class = " gap-below"

            blocks.append(
                f'<details class="developer-message{extra_class}">'
                f'<summary class="role-label">Developer</summary>'
                f'<div class="details-content message-content" style="border-left: 3px solid var(--accent); white-space: pre-wrap;">{content}</div>'
                f"</details>"
            )
        elif isinstance(item, ToolCallItem):
            result = tool_results.get(item.call_id)
            blocks.append(_format_tool_call(item, result))

    return "\n".join(blocks)


def build_export_html(
    session: Session,
    system_prompt: str,
    tools: list[ToolSchema],
    model_name: str,
) -> str:
    """Build HTML export for a session.

    Args:
        session: The session to export.
        system_prompt: The system prompt used.
        tools: List of tools available in the session.
        model_name: The model name used.

    Returns:
        Complete HTML document as a string.
    """
    history = session.conversation_history
    tool_results = {item.call_id: item for item in history if isinstance(item, ToolResultItem)}
    messages_html = _build_messages_html(history, tool_results)
    if not messages_html:
        messages_html = '<div class="text-dim p-4 italic">No messages recorded for this session yet.</div>'

    tools_html = _build_tools_html(tools)
    session_id = session.id
    session_updated = _format_timestamp(session.updated_at)
    work_dir = _shorten_path(str(session.work_dir))
    total_messages = len([item for item in history if not isinstance(item, ToolResultItem)])
    footer_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    first_user_message = get_first_user_message(history)

    template = Template(_load_template())
    return template.substitute(
        session_id=_escape_html(session_id),
        model_name=_escape_html(model_name),
        session_updated=_escape_html(session_updated),
        work_dir=_escape_html(work_dir),
        work_dir_full=_escape_html(str(session.work_dir)),
        system_prompt=_escape_html(system_prompt),
        tools_html=tools_html,
        messages_html=messages_html,
        footer_time=_escape_html(footer_time),
        total_messages=total_messages,
        first_user_message=_escape_html(first_user_message),
        color_bodyBg=COLORS["bodyBg"],
        color_containerBg=COLORS["containerBg"],
        color_cardBg=COLORS["cardBg"],
        color_borderColor=COLORS["borderColor"],
        color_text=COLORS["text"],
        color_textDim=COLORS["textDim"],
        color_cyan=COLORS["cyan"],
        color_green=COLORS["green"],
        color_red=COLORS["red"],
    )
