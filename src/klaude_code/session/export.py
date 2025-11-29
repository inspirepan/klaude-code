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
from klaude_code.protocol import llm_parameter, model

if TYPE_CHECKING:
    from klaude_code.session.session import Session

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


def get_first_user_message(history: list[model.ConversationItem]) -> str:
    """Extract the first user message content from conversation history."""
    for item in history:
        if isinstance(item, model.UserMessageItem) and item.content:
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


def _build_tools_html(tools: list[llm_parameter.ToolSchema]) -> str:
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


def _format_token_count(count: int) -> str:
    if count < 1000:
        return str(count)
    if count < 1000000:
        k = count / 1000
        return f"{int(k)}k" if k.is_integer() else f"{k:.1f}k"
    m = count // 1000000
    rem = (count % 1000000) // 1000
    return f"{m}M" if rem == 0 else f"{m}M{rem}k"


def _render_metadata_item(item: model.ResponseMetadataItem) -> str:
    # Line 1: Model Name [@ Provider]
    model_parts = [f'<span class="metadata-model">{_escape_html(item.model_name)}</span>']
    if item.provider:
        provider = _escape_html(item.provider.lower().replace(" ", "-"))
        model_parts.append(f'<span class="metadata-provider">@{provider}</span>')

    line1 = "".join(model_parts)

    # Line 2: Stats
    stats_parts: list[str] = []
    if item.usage:
        u = item.usage
        stats_parts.append(f'<span class="metadata-stat">input: {_format_token_count(u.input_tokens)}</span>')
        if u.cached_tokens > 0:
            stats_parts.append(f'<span class="metadata-stat">cached: {_format_token_count(u.cached_tokens)}</span>')
        stats_parts.append(f'<span class="metadata-stat">output: {_format_token_count(u.output_tokens)}</span>')
        if u.reasoning_tokens > 0:
            stats_parts.append(
                f'<span class="metadata-stat">thinking: {_format_token_count(u.reasoning_tokens)}</span>'
            )
        if u.context_usage_percent is not None:
            stats_parts.append(f'<span class="metadata-stat">context: {u.context_usage_percent:.1f}%</span>')
        if u.throughput_tps is not None:
            stats_parts.append(f'<span class="metadata-stat">tps: {u.throughput_tps:.1f}</span>')

    if item.task_duration_s is not None:
        stats_parts.append(f'<span class="metadata-stat">cost: {item.task_duration_s:.1f}s</span>')

    stats_html = ""
    if stats_parts:
        divider = '<span class="metadata-divider">/</span>'
        stats_html = divider.join(stats_parts)

    return (
        f'<div class="response-metadata">'
        f'<div class="metadata-line">{line1}</div>'
        f'<div class="metadata-line">{stats_html}</div>'
        f"</div>"
    )


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
        return f'<div style="white-space: pre-wrap; font-family: var(--font-mono);">{content}</div>'

    preview = "\n".join(escaped_lines[:_TOOL_OUTPUT_PREVIEW_LINES])
    full = "\n".join(escaped_lines)

    return (
        f'<div class="expandable-output expandable">'
        f'<div class="preview-text" style="white-space: pre-wrap; font-family: var(--font-mono);">{preview}</div>'
        f'<div class="expand-hint expand-text">Click to expand full output ({len(lines)} lines)</div>'
        f'<div class="full-text" style="white-space: pre-wrap; font-family: var(--font-mono);">{full}</div>'
        f'<div class="collapse-hint">Click to collapse</div>'
        f"</div>"
    )


_COLLAPSIBLE_LINE_THRESHOLD: Final[int] = 100
_COLLAPSIBLE_CHAR_THRESHOLD: Final[int] = 10000


def _should_collapse(text: str) -> bool:
    """Check if content should be collapsed (over 100 lines or 10000 chars)."""
    return text.count("\n") + 1 > _COLLAPSIBLE_LINE_THRESHOLD or len(text) > _COLLAPSIBLE_CHAR_THRESHOLD


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
    diff_content = f'<div class="diff-view">{"".join(rendered)}</div>'
    open_attr = "" if _should_collapse(diff) else " open"
    return (
        f'<details class="diff-collapsible"{open_attr}>'
        f"<summary>Diff ({len(lines)} lines)</summary>"
        f"{diff_content}"
        "</details>"
    )


def _get_diff_text(ui_extra: model.ToolResultUIExtra | None) -> str | None:
    if ui_extra is None:
        return None
    if ui_extra.type != model.ToolResultUIExtraType.DIFF_TEXT:
        return None
    return ui_extra.diff_text


def _get_mermaid_link_html(
    ui_extra: model.ToolResultUIExtra | None, tool_call: model.ToolCallItem | None = None
) -> str | None:
    if ui_extra is None:
        return None
    if ui_extra.type != model.ToolResultUIExtraType.MERMAID_LINK:
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


def _format_tool_call(tool_call: model.ToolCallItem, result: model.ToolResultItem | None) -> str:
    args_html = None
    is_todo_list = False
    if tool_call.name == "TodoWrite":
        args_html = _try_render_todo_args(tool_call.arguments)
        if args_html:
            is_todo_list = True

    if args_html is None:
        try:
            parsed = json.loads(tool_call.arguments)
            args_text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            args_text = tool_call.arguments

        args_html = _escape_html(args_text or "")

    if not args_html:
        args_html = '<span style="color: var(--text-dim); font-style: italic;">(no arguments)</span>'

    # Wrap tool-args with collapsible details element (except for TodoWrite which renders as a list)
    if is_todo_list:
        args_section = f'<div class="tool-args">{args_html}</div>'
    else:
        open_attr = "" if _should_collapse(args_html) else " open"
        args_section = (
            f'<details class="tool-args-collapsible"{open_attr}>'
            "<summary>Arguments</summary>"
            f'<div class="tool-args-content">{args_html}</div>'
            "</details>"
        )

    html_parts = [
        '<div class="tool-call">',
        '<div class="tool-header">',
        f'<span class="tool-name">{_escape_html(tool_call.name)}</span>',
        f'<span class="tool-id">{_escape_html(tool_call.call_id)}</span>',
        "</div>",
        args_section,
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
    history: list[model.ConversationItem],
    tool_results: dict[str, model.ToolResultItem],
) -> str:
    blocks: list[str] = []
    assistant_counter = 0

    renderable_items = [
        item for item in history if not isinstance(item, (model.ToolResultItem, model.ReasoningEncryptedItem))
    ]

    for i, item in enumerate(renderable_items):
        if isinstance(item, model.UserMessageItem):
            text = _escape_html(item.content or "")
            blocks.append(
                f'<div class="message-group">'
                f'<div class="role-label user">User</div>'
                f'<div class="message-content user" style="white-space: pre-wrap;">{text}</div>'
                f"</div>"
            )
        elif isinstance(item, model.ReasoningTextItem):
            text = _escape_html(item.content.strip())
            blocks.append(f'<div class="thinking-block">{text.replace(chr(10), "<br>")}</div>')
        elif isinstance(item, model.AssistantMessageItem):
            assistant_counter += 1
            blocks.append(_render_assistant_message(assistant_counter, item.content or ""))
        elif isinstance(item, model.ResponseMetadataItem):
            blocks.append(_render_metadata_item(item))
        elif isinstance(item, model.DeveloperMessageItem):
            content = _escape_html(item.content or "")

            next_item = renderable_items[i + 1] if i + 1 < len(renderable_items) else None
            extra_class = ""
            if isinstance(next_item, (model.UserMessageItem, model.AssistantMessageItem)):
                extra_class = " gap-below"

            blocks.append(
                f'<details class="developer-message{extra_class}">'
                f"<summary>Developer</summary>"
                f'<div class="details-content" style="white-space: pre-wrap;">{content}</div>'
                f"</details>"
            )
        elif isinstance(item, model.ToolCallItem):
            result = tool_results.get(item.call_id)
            blocks.append(_format_tool_call(item, result))

    return "\n".join(blocks)


def build_export_html(
    session: Session,
    system_prompt: str,
    tools: list[llm_parameter.ToolSchema],
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
    tool_results = {item.call_id: item for item in history if isinstance(item, model.ToolResultItem)}
    messages_html = _build_messages_html(history, tool_results)
    if not messages_html:
        messages_html = '<div class="text-dim p-4 italic">No messages recorded for this session yet.</div>'

    tools_html = _build_tools_html(tools)
    session_id = session.id
    session_updated = _format_timestamp(session.updated_at)
    work_dir = _shorten_path(str(session.work_dir))
    total_messages = len([item for item in history if not isinstance(item, model.ToolResultItem)])
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
    )
