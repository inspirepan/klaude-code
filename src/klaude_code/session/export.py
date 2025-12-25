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

from klaude_code.protocol import llm_param, model
from klaude_code.protocol.sub_agent import is_sub_agent_tool

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


def _format_msg_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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

    exports_dir = SessionClass.exports_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    first_msg = get_first_user_message(session.conversation_history)
    sanitized_msg = _sanitize_filename(first_msg)
    filename = f"{timestamp}_{sanitized_msg}.html"
    return exports_dir / filename


def _load_template() -> str:
    """Load the HTML template from the templates directory."""
    template_file = importlib.resources.files("klaude_code.session.templates").joinpath("export_session.html")
    return template_file.read_text(encoding="utf-8")


def _build_tools_html(tools: list[llm_param.ToolSchema]) -> str:
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


def _format_cost(cost: float, currency: str = "USD") -> str:
    symbol = "¥" if currency == "CNY" else "$"
    return f"{symbol}{cost:.4f}"


def _render_single_metadata(
    metadata: model.TaskMetadata,
    *,
    indent: int = 0,
    show_context: bool = True,
) -> str:
    """Render a single TaskMetadata block as HTML.

    Args:
        metadata: The TaskMetadata to render.
        indent: Number of spaces to indent (0 for main, 2 for sub-agents).
        show_context: Whether to show context usage percent.

    Returns:
        HTML string for this metadata block.
    """
    parts: list[str] = []

    # Model Name [@ Provider]
    model_parts = [f'<span class="metadata-model">{_escape_html(metadata.model_name)}</span>']
    if metadata.provider:
        provider = _escape_html(metadata.provider.lower().replace(" ", "-"))
        model_parts.append(f'<span class="metadata-provider">@{provider}</span>')

    parts.append("".join(model_parts))

    # Stats
    if metadata.usage:
        u = metadata.usage
        # Input with cost
        input_stat = f"input: {_format_token_count(u.input_tokens)}"
        if u.input_cost is not None:
            input_stat += f"({_format_cost(u.input_cost, u.currency)})"
        parts.append(f'<span class="metadata-stat">{input_stat}</span>')

        # Cached with cost
        if u.cached_tokens > 0:
            cached_stat = f"cached: {_format_token_count(u.cached_tokens)}"
            if u.cache_read_cost is not None:
                cached_stat += f"({_format_cost(u.cache_read_cost, u.currency)})"
            parts.append(f'<span class="metadata-stat">{cached_stat}</span>')

        # Output with cost
        output_stat = f"output: {_format_token_count(u.output_tokens)}"
        if u.output_cost is not None:
            output_stat += f"({_format_cost(u.output_cost, u.currency)})"
        parts.append(f'<span class="metadata-stat">{output_stat}</span>')

        if u.reasoning_tokens > 0:
            parts.append(f'<span class="metadata-stat">thinking: {_format_token_count(u.reasoning_tokens)}</span>')
        if show_context and u.context_usage_percent is not None:
            parts.append(f'<span class="metadata-stat">context: {u.context_usage_percent:.1f}%</span>')
        if u.throughput_tps is not None:
            parts.append(f'<span class="metadata-stat">tps: {u.throughput_tps:.1f}</span>')

    if metadata.task_duration_s is not None:
        parts.append(f'<span class="metadata-stat">time: {metadata.task_duration_s:.1f}s</span>')

    # Total cost
    if metadata.usage is not None and metadata.usage.total_cost is not None:
        parts.append(
            f'<span class="metadata-stat">cost: {_format_cost(metadata.usage.total_cost, metadata.usage.currency)}</span>'
        )

    divider = '<span class="metadata-divider">/</span>'
    joined_html = divider.join(parts)

    indent_style = f' style="padding-left: {indent}em;"' if indent > 0 else ""
    return f'<div class="metadata-line"{indent_style}>{joined_html}</div>'


def _render_metadata_item(item: model.TaskMetadataItem) -> str:
    """Render TaskMetadataItem including main agent and sub-agents."""
    lines: list[str] = []

    # Main agent metadata
    lines.append(_render_single_metadata(item.main_agent, indent=0, show_context=True))

    # Sub-agent metadata with indent
    for sub in item.sub_agent_task_metadata:
        lines.append(_render_single_metadata(sub, indent=1, show_context=False))

    return f'<div class="response-metadata">{"".join(lines)}</div>'


def _render_assistant_message(index: int, content: str, timestamp: datetime) -> str:
    encoded = _escape_html(content)
    ts_str = _format_msg_timestamp(timestamp)
    return (
        f'<div class="message-group assistant-message-group">'
        f'<div class="message-header">'
        f'<div class="role-label assistant">Assistant</div>'
        f'<div class="assistant-toolbar">'
        f'<span class="timestamp">{ts_str}</span>'
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


def _try_render_todo_args(arguments: str, tool_name: str) -> str | None:
    try:
        parsed = json.loads(arguments)
        if not isinstance(parsed, dict):
            return None

        # Support both TodoWrite (todos/content) and update_plan (plan/step)
        parsed_dict = cast(dict[str, Any], parsed)
        if tool_name == "TodoWrite":
            items = parsed_dict.get("todos")
            content_key = "content"
        elif tool_name == "update_plan":
            items = parsed_dict.get("plan")
            content_key = "step"
        else:
            return None

        if not isinstance(items, list) or not items:
            return None

        items_html: list[str] = []
        for item in cast(list[dict[str, str]], items):
            content = _escape_html(item.get(content_key, ""))
            status = item.get("status", "pending")
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
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _render_sub_agent_result(content: str) -> str:
    # Try to format as JSON for better readability
    try:
        parsed = json.loads(content)
        formatted = "```json\n" + json.dumps(parsed, ensure_ascii=False, indent=2) + "\n```"
    except (json.JSONDecodeError, TypeError):
        formatted = content
    encoded = _escape_html(formatted)
    return (
        f'<div class="sub-agent-result-container">'
        f'<div class="sub-agent-toolbar">'
        f'<button type="button" class="raw-toggle" aria-pressed="false" title="Toggle raw text view">Raw</button>'
        f'<button type="button" class="copy-raw-btn" title="Copy raw content">Copy</button>'
        f"</div>"
        f'<div class="sub-agent-content">'
        f'<div class="sub-agent-rendered markdown-content markdown-body" data-raw="{encoded}">'
        f'<noscript><pre style="white-space: pre-wrap;">{encoded}</pre></noscript>'
        f"</div>"
        f'<pre class="sub-agent-raw">{encoded}</pre>'
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
        f'<div class="expand-hint expand-text">click to expand full output ({len(lines)} lines)</div>'
        f'<div class="full-text" style="white-space: pre-wrap; font-family: var(--font-mono);">{full}</div>'
        f'<div class="collapse-hint">click to collapse</div>'
        f"</div>"
    )


_COLLAPSIBLE_LINE_THRESHOLD: Final[int] = 100
_COLLAPSIBLE_CHAR_THRESHOLD: Final[int] = 10000


def _should_collapse(text: str) -> bool:
    """Check if content should be collapsed (over 100 lines or 10000 chars)."""
    return text.count("\n") + 1 > _COLLAPSIBLE_LINE_THRESHOLD or len(text) > _COLLAPSIBLE_CHAR_THRESHOLD


def _render_diff_block(diff: model.DiffUIExtra) -> str:
    rendered: list[str] = []
    line_count = 0

    for file_diff in diff.files:
        header = _render_diff_file_header(file_diff)
        if header:
            rendered.append(header)
        for line in file_diff.lines:
            rendered.append(_render_diff_line(line))
            line_count += 1

    if line_count == 0:
        rendered.append('<span class="diff-line diff-ctx">&nbsp;</span>')

    diff_content = f'<div class="diff-view">{"".join(rendered)}</div>'
    open_attr = "" if _should_collapse("\n" * max(1, line_count)) else " open"
    return (
        f'<details class="diff-collapsible"{open_attr}>'
        f"<summary>Diff ({line_count} lines)</summary>"
        f"{diff_content}"
        "</details>"
    )


def _render_diff_file_header(file_diff: model.DiffFileDiff) -> str:
    stats_parts: list[str] = []
    if file_diff.stats_add > 0:
        stats_parts.append(f'<span class="diff-stats-add">+{file_diff.stats_add}</span>')
    if file_diff.stats_remove > 0:
        stats_parts.append(f'<span class="diff-stats-remove">-{file_diff.stats_remove}</span>')
    stats_html = f' <span class="diff-stats">{" ".join(stats_parts)}</span>' if stats_parts else ""
    file_name = _escape_html(file_diff.file_path)
    return f'<div class="diff-file">{file_name}{stats_html}</div>'


def _render_diff_line(line: model.DiffLine) -> str:
    if line.kind == "gap":
        line_class = "diff-ctx"
        prefix = "⋮"
    else:
        line_class = "diff-plus" if line.kind == "add" else "diff-minus" if line.kind == "remove" else "diff-ctx"
        prefix = "+" if line.kind == "add" else "-" if line.kind == "remove" else " "
    spans = [_render_diff_span(span, line.kind) for span in line.spans]
    content = "".join(spans)
    if not content:
        content = "&nbsp;"
    return f'<span class="diff-line {line_class}">{prefix} {content}</span>'


def _render_diff_span(span: model.DiffSpan, line_kind: str) -> str:
    text = _escape_html(span.text)
    if line_kind == "add" and span.op == "insert":
        return f'<span class="diff-span diff-char-add">{text}</span>'
    if line_kind == "remove" and span.op == "delete":
        return f'<span class="diff-span diff-char-remove">{text}</span>'
    return f'<span class="diff-span">{text}</span>'


def _render_markdown_doc(doc: model.MarkdownDocUIExtra) -> str:
    encoded = _escape_html(doc.content)
    file_path = _escape_html(doc.file_path)
    header = f'<div class="diff-file">{file_path} <span style="font-weight: normal; color: var(--text-dim); font-size: 12px; margin-left: 8px;">(markdown content)</span></div>'

    # Using a container that mimics diff-view but for markdown
    content = (
        f'<div class="markdown-content markdown-body" data-raw="{encoded}" '
        f'style="padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-body); margin-top: 4px;">'
        f'<noscript><pre style="white-space: pre-wrap;">{encoded}</pre></noscript>'
        f"</div>"
    )

    line_count = doc.content.count("\n") + 1
    open_attr = " open"

    return (
        f'<details class="diff-collapsible"{open_attr}>'
        f"<summary>File Content ({line_count} lines)</summary>"
        f'<div style="margin-top: 8px;">'
        f"{header}"
        f"{content}"
        f"</div>"
        f"</details>"
    )


def _collect_ui_extras(ui_extra: model.ToolResultUIExtra | None) -> list[model.ToolResultUIExtra]:
    if ui_extra is None:
        return []
    if isinstance(ui_extra, model.MultiUIExtra):
        return list(ui_extra.items)
    return [ui_extra]


def _build_add_only_diff(text: str, file_path: str) -> model.DiffUIExtra:
    lines: list[model.DiffLine] = []
    new_line_no = 1
    for line in text.splitlines():
        lines.append(
            model.DiffLine(
                kind="add",
                new_line_no=new_line_no,
                spans=[model.DiffSpan(op="equal", text=line)],
            )
        )
        new_line_no += 1
    file_diff = model.DiffFileDiff(file_path=file_path, lines=lines, stats_add=len(lines), stats_remove=0)
    return model.DiffUIExtra(files=[file_diff])


def _get_mermaid_link_html(
    ui_extra: model.ToolResultUIExtra | None, tool_call: model.ToolCallItem | None = None
) -> str | None:
    code = ""
    link: str | None = None
    line_count = 0

    if isinstance(ui_extra, model.MermaidLinkUIExtra):
        code = ui_extra.code
        link = ui_extra.link
        line_count = ui_extra.line_count

    if not code and tool_call and tool_call.name == "Mermaid":
        try:
            args = json.loads(tool_call.arguments)
            code = args.get("code", "")
        except (json.JSONDecodeError, TypeError):
            code = ""
        line_count = code.count("\n") + 1 if code else 0

    if not code and not link:
        return None

    # Prepare code for rendering and copy
    escaped_code = _escape_html(code) if code else ""

    # Build Toolbar
    toolbar_items: list[str] = []

    if line_count > 0:
        toolbar_items.append(f"<span>Lines: {line_count}</span>")

    buttons_html: list[str] = []
    if code:
        buttons_html.append(
            f'<button type="button" class="copy-mermaid-btn" data-code="{escaped_code}" title="Copy Mermaid Code">Copy Code</button>'
        )
        buttons_html.append(
            '<button type="button" class="fullscreen-mermaid-btn" title="View Fullscreen">Fullscreen</button>'
        )

    if link:
        link_url = _escape_html(link)
        buttons_html.append(
            f'<a href="{link_url}" target="_blank" rel="noopener noreferrer" style="color: var(--accent); text-decoration: underline; margin-left: 8px;">View Online</a>'
        )

    toolbar_items.append(f"<div>{''.join(buttons_html)}</div>")

    toolbar_html = (
        '<div style="display: flex; justify-content: space-between; align-items: center; font-family: var(--font-mono); margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border);">'
        f"{''.join(toolbar_items)}"
        "</div>"
    )

    # If we have code, render the diagram
    if code:
        return (
            f'<div style="background: white; padding: 16px; border-radius: 4px; margin-top: 8px; border: 1px solid var(--border);">'
            f'<div class="mermaid">{escaped_code}</div>'
            f"{toolbar_html}"
            f"</div>"
        )

    # Fallback to just link/toolbar if no code available (legacy support behavior)
    return toolbar_html


def _format_tool_call(tool_call: model.ToolCallItem, result: model.ToolResultItem | None) -> str:
    args_html = None
    is_todo_list = False
    ts_str = _format_msg_timestamp(tool_call.created_at)

    if tool_call.name in ("TodoWrite", "update_plan"):
        args_html = _try_render_todo_args(tool_call.arguments, tool_call.name)
        if args_html:
            is_todo_list = True

    if args_html is None:
        try:
            parsed = json.loads(tool_call.arguments)
            args_text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            args_text = tool_call.arguments

        args_html = _escape_html(args_text or "")

    if not args_html:
        args_html = '<span style="color: var(--text-dim); font-style: italic;">(no arguments)</span>'

    # Wrap tool-args with collapsible details element (except for TodoWrite which renders as a list)
    if is_todo_list:
        args_section = f'<div class="tool-args">{args_html}</div>'
    else:
        # Always collapse Mermaid, Edit, Write tools by default
        always_collapse_tools = {"Mermaid", "Edit", "Write"}
        force_collapse = tool_call.name in always_collapse_tools

        # Collapse Memory tool for write operations
        if tool_call.name == "Memory":
            try:
                parsed_args = json.loads(tool_call.arguments)
                if parsed_args.get("command") in {"create", "str_replace", "insert"}:
                    force_collapse = True
            except (json.JSONDecodeError, TypeError):
                pass

        should_collapse = force_collapse or _should_collapse(args_html)
        open_attr = "" if should_collapse else " open"
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
        '<div class="tool-header-right">',
        f'<span class="tool-id">{_escape_html(tool_call.call_id)}</span>',
        f'<span class="timestamp">{ts_str}</span>',
        "</div>",
        "</div>",
        args_section,
    ]

    if result:
        extras = _collect_ui_extras(result.ui_extra)

        mermaid_extra = next((x for x in extras if isinstance(x, model.MermaidLinkUIExtra)), None)
        mermaid_source = mermaid_extra if mermaid_extra else result.ui_extra
        mermaid_html = _get_mermaid_link_html(mermaid_source, tool_call)

        should_hide_text = tool_call.name in ("TodoWrite", "update_plan") and result.status != "error"

        if (
            tool_call.name == "Edit"
            and not any(isinstance(x, model.DiffUIExtra) for x in extras)
            and result.status != "error"
        ):
            try:
                args_data = json.loads(tool_call.arguments)
                file_path = args_data.get("file_path", "Unknown file")
                old_string = args_data.get("old_string", "")
                new_string = args_data.get("new_string", "")
                if old_string == "" and new_string:
                    extras.append(_build_add_only_diff(new_string, file_path))
            except (json.JSONDecodeError, TypeError):
                pass

        items_to_render: list[str] = []

        if result.output and not should_hide_text:
            if is_sub_agent_tool(tool_call.name):
                items_to_render.append(_render_sub_agent_result(result.output))
            else:
                items_to_render.append(_render_text_block(result.output))

        for extra in extras:
            if isinstance(extra, model.DiffUIExtra):
                items_to_render.append(_render_diff_block(extra))
            elif isinstance(extra, model.MarkdownDocUIExtra):
                items_to_render.append(_render_markdown_doc(extra))

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
    *,
    seen_session_ids: set[str] | None = None,
    nesting_level: int = 0,
) -> str:
    if seen_session_ids is None:
        seen_session_ids = set()

    blocks: list[str] = []
    assistant_counter = 0

    renderable_items = [
        item for item in history if not isinstance(item, (model.ToolResultItem, model.ReasoningEncryptedItem))
    ]

    for i, item in enumerate(renderable_items):
        if isinstance(item, model.UserMessageItem):
            text = _escape_html(item.content or "")
            ts_str = _format_msg_timestamp(item.created_at)
            blocks.append(
                f'<div class="message-group">'
                f'<div class="role-label user">'
                f"User"
                f'<span class="timestamp">{ts_str}</span>'
                f"</div>"
                f'<div class="message-content user" style="white-space: pre-wrap;">{text}</div>'
                f"</div>"
            )
        elif isinstance(item, model.ReasoningTextItem):
            text = _escape_html(item.content.strip())
            blocks.append(f'<div class="thinking-block markdown-body markdown-content" data-raw="{text}"></div>')
        elif isinstance(item, model.AssistantMessageItem):
            assistant_counter += 1
            blocks.append(_render_assistant_message(assistant_counter, item.content or "", item.created_at))
        elif isinstance(item, model.TaskMetadataItem):
            blocks.append(_render_metadata_item(item))
        elif isinstance(item, model.DeveloperMessageItem):
            content = _escape_html(item.content or "")
            ts_str = _format_msg_timestamp(item.created_at)

            next_item = renderable_items[i + 1] if i + 1 < len(renderable_items) else None
            extra_class = ""
            if isinstance(next_item, (model.UserMessageItem, model.AssistantMessageItem)):
                extra_class = " gap-below"

            blocks.append(
                f'<details class="developer-message{extra_class}">'
                f"<summary>"
                f"Developer"
                f'<span class="timestamp">{ts_str}</span>'
                f"</summary>"
                f'<div class="details-content" style="white-space: pre-wrap;">{content}</div>'
                f"</details>"
            )

        elif isinstance(item, model.ToolCallItem):
            result = tool_results.get(item.call_id)
            blocks.append(_format_tool_call(item, result))

            # Recursively render sub-agent session history
            if result is not None:
                sub_agent_html = _render_sub_agent_session(result, seen_session_ids, nesting_level)
                if sub_agent_html:
                    blocks.append(sub_agent_html)

    return "\n".join(blocks)


def _render_sub_agent_session(
    tool_result: model.ToolResultItem,
    seen_session_ids: set[str],
    nesting_level: int,
) -> str | None:
    """Render sub-agent session history when a tool result references it."""
    from klaude_code.session.session import Session

    ui_extra = tool_result.ui_extra
    if not isinstance(ui_extra, model.SessionIdUIExtra):
        return None

    session_id = ui_extra.session_id
    if not session_id or session_id in seen_session_ids:
        return None

    seen_session_ids.add(session_id)

    try:
        sub_session = Session.load(session_id)
    except (OSError, json.JSONDecodeError, ValueError):
        return None

    sub_history = sub_session.conversation_history
    sub_tool_results = {item.call_id: item for item in sub_history if isinstance(item, model.ToolResultItem)}

    sub_html = _build_messages_html(
        sub_history,
        sub_tool_results,
        seen_session_ids=seen_session_ids,
        nesting_level=nesting_level + 1,
    )

    if not sub_html:
        return None

    # Wrap in a collapsible sub-agent container using same style as other collapsible sections
    indent_style = f' style="margin-left: {nesting_level * 16}px;"' if nesting_level > 0 else ""
    return (
        f'<details class="sub-agent-session"{indent_style}>'
        f"<summary>Sub-agent: {_escape_html(session_id)}</summary>"
        f'<div class="sub-agent-content">{sub_html}</div>'
        f"</details>"
    )


def build_export_html(
    session: Session,
    system_prompt: str,
    tools: list[llm_param.ToolSchema],
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
