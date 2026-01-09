"""Session export functionality for generating HTML transcripts."""

from __future__ import annotations

import base64
import html
import importlib.resources
import json
import mimetypes
import re
from datetime import datetime
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any, Final, cast

from klaude_code.protocol import llm_param, message, model
from klaude_code.protocol.sub_agent import is_sub_agent_tool

if TYPE_CHECKING:
    from klaude_code.session.session import Session

_TOOL_OUTPUT_PREVIEW_LINES: Final[int] = 8
_MAX_FILENAME_MESSAGE_LEN: Final[int] = 50
_IMAGE_MAX_DISPLAY_WIDTH: Final[int] = 600


def _image_to_data_url(file_path: str) -> str | None:
    """Read an image file and convert it to a base64 data URL.

    Returns None if the file doesn't exist or can't be read.
    """
    path = Path(file_path)
    if not path.exists():
        return None

    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"

    try:
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime_type};base64,{b64}"
    except OSError:
        return None


def _render_image_html(file_path: str, max_width: int = _IMAGE_MAX_DISPLAY_WIDTH) -> str:
    """Render an image as HTML img tag with base64 data URL."""
    data_url = _image_to_data_url(file_path)
    if data_url:
        short_path = _shorten_path(file_path)
        return (
            f'<div class="assistant-image" style="margin: 8px 0;">'
            f'<img src="{data_url}" alt="Generated image" '
            f'style="max-width: {max_width}px; border-radius: 4px; border: 1px solid var(--border);" />'
            f'<div style="font-size: 12px; color: var(--text-dim); margin-top: 4px;">{_escape_html(short_path)}</div>'
            f"</div>"
        )
    short_path = _shorten_path(file_path)
    return f'<div class="assistant-image-missing" style="color: var(--text-dim); font-style: italic;">Image not found: {_escape_html(short_path)}</div>'


def _render_image_url_html(url: str, max_width: int = _IMAGE_MAX_DISPLAY_WIDTH) -> str:
    """Render an image URL as HTML img tag."""
    short_url = _escape_html(_shorten_path(url))
    caption = ""
    if not url.startswith("data:"):
        caption = f'<div style="font-size: 12px; color: var(--text-dim); margin-top: 4px;">{short_url}</div>'
    return (
        f'<div class="assistant-image" style="margin: 8px 0;">'
        f'<img src="{_escape_html(url)}" alt="Image" '
        f'style="max-width: {max_width}px; border-radius: 4px; border: 1px solid var(--border);" />'
        f"{caption}"
        f"</div>"
    )


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


def get_first_user_message(history: list[message.HistoryEvent]) -> str:
    """Extract the first user message content from conversation history."""
    for item in history:
        if isinstance(item, message.UserMessage):
            content = message.join_text_parts(item.parts).strip()
            if not content:
                continue
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


def _render_assistant_message(
    index: int,
    content: str,
    timestamp: datetime,
    images: list[message.ImageFilePart | message.ImageURLPart] | None = None,
) -> str:
    encoded = _escape_html(content)
    ts_str = _format_msg_timestamp(timestamp)

    images_html = ""
    if images:
        images_parts: list[str] = []
        for img in images:
            if isinstance(img, message.ImageFilePart):
                images_parts.append(_render_image_html(img.file_path))
            else:
                images_parts.append(_render_image_url_html(img.url))
        images_html = "".join(images_parts)

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
        f"{images_html}"
        f'<div class="assistant-rendered markdown-content markdown-body" data-raw="{encoded}">'
        f'<noscript><pre style="white-space: pre-wrap;">{encoded}</pre></noscript>'
        f"</div>"
        f'<pre class="assistant-raw">{encoded}</pre>'
        f"</div>"
        f"</div>"
    )


def _extract_image_parts(parts: list[message.Part]) -> list[message.ImageFilePart | message.ImageURLPart]:
    images: list[message.ImageFilePart | message.ImageURLPart] = []
    for part in parts:
        if isinstance(part, (message.ImageFilePart, message.ImageURLPart)):
            images.append(part)
    return images


def _render_image_parts(images: list[message.ImageFilePart | message.ImageURLPart]) -> str:
    rendered: list[str] = []
    for img in images:
        if isinstance(img, message.ImageFilePart):
            rendered.append(_render_image_html(img.file_path))
        else:
            rendered.append(_render_image_url_html(img.url))
    return "".join(rendered)


def _render_thinking_block(text: str) -> str:
    encoded = _escape_html(text.strip())
    return f'<div class="thinking-block markdown-body markdown-content" data-raw="{encoded}"></div>'


class _TurnGroup:
    def __init__(self) -> None:
        self.user_message: message.UserMessage | None = None
        self.body_items: list[message.HistoryEvent] = []


def _group_messages_by_turn(history: list[message.HistoryEvent]) -> list[_TurnGroup]:
    groups: list[_TurnGroup] = []
    current_group = _TurnGroup()

    # Filter for renderable items only
    renderable_items = [item for item in history if not isinstance(item, message.ToolResultMessage)]

    for item in renderable_items:
        if isinstance(item, message.UserMessage):
            # If current group has content, save it and start new
            if current_group.user_message or current_group.body_items:
                groups.append(current_group)
            current_group = _TurnGroup()
            current_group.user_message = item
        else:
            current_group.body_items.append(item)

    # Append the last group if it has content
    if current_group.user_message or current_group.body_items:
        groups.append(current_group)

    return groups


def _render_event_item(
    item: message.HistoryEvent,
    tool_results: dict[str, message.ToolResultMessage],
    seen_session_ids: set[str],
    nesting_level: int,
    assistant_counter: list[int],
) -> str:
    blocks: list[str] = []

    if isinstance(item, message.UserMessage):
        text = message.join_text_parts(item.parts)
        images = _extract_image_parts(item.parts)
        images_html = _render_image_parts(images)
        ts_str = _format_msg_timestamp(item.created_at)
        body_parts: list[str] = []
        if images_html:
            body_parts.append(images_html)
        if text:
            body_parts.append(f'<div style="white-space: pre-wrap;">{_escape_html(text)}</div>')
        if not body_parts:
            body_parts.append('<div style="color: var(--text-dim); font-style: italic;">(empty)</div>')
        blocks.append(
            f'<div class="message-group">'
            f'<div class="role-label user">'
            f"User"
            f'<span class="timestamp">{ts_str}</span>'
            f"</div>"
            f'<div class="message-content user">{"".join(body_parts)}</div>'
            f"</div>"
        )
    elif isinstance(item, message.AssistantMessage):
        assistant_counter[0] += 1
        thinking_text = "".join(part.text for part in item.parts if isinstance(part, message.ThinkingTextPart))
        if thinking_text:
            blocks.append(_render_thinking_block(thinking_text))

        assistant_text = message.join_text_parts(item.parts)
        assistant_images = _extract_image_parts(item.parts)
        if assistant_text or assistant_images:
            blocks.append(
                _render_assistant_message(
                    assistant_counter[0],
                    assistant_text,
                    item.created_at,
                    assistant_images,
                )
            )

        for part in item.parts:
            if isinstance(part, message.ToolCallPart):
                result = tool_results.get(part.call_id)
                blocks.append(_format_tool_call(part, result, item.created_at))
                if result is not None:
                    sub_agent_html = _render_sub_agent_session(result, seen_session_ids, nesting_level)
                    if sub_agent_html:
                        blocks.append(sub_agent_html)
    elif isinstance(item, model.TaskMetadataItem):
        blocks.append(_render_metadata_item(item))
    elif isinstance(item, message.DeveloperMessage):
        content = message.join_text_parts(item.parts)
        images = _extract_image_parts(item.parts)
        images_html = _render_image_parts(images)
        ts_str = _format_msg_timestamp(item.created_at)

        detail_body = ""
        if images_html:
            detail_body += images_html
        if content:
            detail_body += f'<div style="white-space: pre-wrap;">{_escape_html(content)}</div>'
        if not detail_body:
            detail_body = '<div style="color: var(--text-dim); font-style: italic;">(empty)</div>'

        blocks.append(
            f'<details class="developer-message gap-below">'
            f"<summary>"
            f"Developer"
            f'<span class="timestamp">{ts_str}</span>'
            f"</summary>"
            f'<div class="details-content">{detail_body}</div>'
            f"</details>"
        )
    elif isinstance(item, message.SystemMessage):
        content = message.join_text_parts(item.parts)
        if content:
            ts_str = _format_msg_timestamp(item.created_at)
            blocks.append(
                f'<details class="developer-message">'
                f"<summary>"
                f"System"
                f'<span class="timestamp">{ts_str}</span>'
                f"</summary>"
                f'<div class="details-content" style="white-space: pre-wrap;">{_escape_html(content)}</div>'
                f"</details>"
            )

    return "".join(blocks)


def _has_non_mermaid_tool(msg: message.AssistantMessage) -> bool:
    has_non_mermaid = False
    for part in msg.parts:
        if isinstance(part, message.ToolCallPart):
            if part.tool_name != "Mermaid":
                has_non_mermaid = True
            else:
                # If it has Mermaid, we treat it as visible, overriding the non-mermaid flag
                # for the purpose of finding the BARRIER.
                # Logic: We want to find the LAST item that is STRICTLY non-mermaid/intermediate.
                # If an item has Mermaid, it belongs to the visible chain.
                return False
    return has_non_mermaid


def _build_messages_html(
    history: list[message.HistoryEvent],
    tool_results: dict[str, message.ToolResultMessage],
    *,
    seen_session_ids: set[str] | None = None,
    nesting_level: int = 0,
) -> str:
    if seen_session_ids is None:
        seen_session_ids = set()

    blocks: list[str] = []
    assistant_counter = [0]  # Use list for mutable reference

    turns = _group_messages_by_turn(history)

    for turn in turns:
        # 1. Render User Message
        if turn.user_message:
            blocks.append(
                _render_event_item(turn.user_message, tool_results, seen_session_ids, nesting_level, assistant_counter)
            )

        if not turn.body_items:
            continue

        # 2. Identify split point (barrier)
        # Find the LAST AssistantMessage that has a non-Mermaid tool call (and NO Mermaid tool call).
        barrier_index = -1
        for i, item in enumerate(turn.body_items):
            if isinstance(item, message.AssistantMessage) and _has_non_mermaid_tool(item):
                barrier_index = i

        # If barrier found, everything up to it is collapsible.
        # Everything after is visible.
        # If no barrier (-1), checks depend on if we have any AssistantMessages
        collapsible_items = []
        visible_items = []

        if barrier_index != -1:
            collapsible_items = turn.body_items[: barrier_index + 1]
            visible_items = turn.body_items[barrier_index + 1 :]
        else:
            # No barrier found (no non-Mermaid tools).
            # If purely conversational, all visible?
            # Or should we fold intermediate chat steps?
            # Current logic: If no tools used, assume chat mode -> All visible.
            collapsible_items = []
            visible_items = turn.body_items

        # 3. Render Collapsible Items
        if collapsible_items:
            # Count steps (assistant messages + tool calls approx)
            step_count = sum(1 for item in collapsible_items if isinstance(item, message.AssistantMessage))
            step_label = f"{step_count} steps" if step_count != 1 else "1 step"

            collapsed_html = "".join(
                _render_event_item(item, tool_results, seen_session_ids, nesting_level, assistant_counter)
                for item in collapsible_items
            )

            blocks.append(
                f'<div class="turn-collapsible">'
                f'<button class="turn-collapse-btn" title="Show/hide intermediate steps">'
                f'<span class="collapse-icon">[+]</span>'
                f'<span class="collapse-count">{step_label}</span>'
                f"</button>"
                f'<div class="turn-steps" style="display: none;">'
                f"{collapsed_html}"
                f"</div>"
                f"</div>"
            )

        # 4. Render Visible Items
        for item in visible_items:
            blocks.append(_render_event_item(item, tool_results, seen_session_ids, nesting_level, assistant_counter))

    return "\n".join(blocks)


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


def _extract_saved_images(content: str) -> tuple[str, list[str]]:
    """Extract image paths from 'Saved images:' section in content.

    Returns:
        Tuple of (remaining_text, list_of_image_paths).
    """
    image_paths: list[str] = []
    lines = content.splitlines()
    result_lines: list[str] = []
    in_saved_images = False

    for line in lines:
        stripped = line.strip()
        if stripped == "Saved images:":
            in_saved_images = True
            continue
        if in_saved_images:
            if stripped.startswith("- "):
                path = stripped[2:].strip()
                if path:
                    image_paths.append(path)
                continue
            # End of saved images section (non-list line)
            in_saved_images = False
        result_lines.append(line)

    return "\n".join(result_lines).strip(), image_paths


def _render_sub_agent_result(content: str, description: str | None = None) -> str:
    # Extract saved images from content
    text_content, image_paths = _extract_saved_images(content)

    # Render images first
    images_html = ""
    if image_paths:
        images_parts = [_render_image_html(path) for path in image_paths]
        images_html = "".join(images_parts)

    # Try to format remaining text as JSON for better readability
    try:
        parsed = json.loads(text_content)
        formatted = "```json\n" + json.dumps(parsed, ensure_ascii=False, indent=2) + "\n```"
    except (json.JSONDecodeError, TypeError):
        formatted = text_content

    if description:
        formatted = f"# {description}\n\n{formatted}"

    encoded = _escape_html(formatted)

    # If we have images but no text, just show images
    if images_html and not formatted.strip():
        return f'<div class="sub-agent-result-container">{images_html}</div>'

    # Check if content needs collapsing (approx > 20 lines or > 2000 chars)
    # Using a simpler metric since we don't know rendered height
    needs_collapse = formatted.count("\n") > 20 or len(formatted) > 2000

    rendered_html = (
        f'<div class="sub-agent-rendered markdown-content markdown-body" data-raw="{encoded}">'
        f'<noscript><pre style="white-space: pre-wrap;">{encoded}</pre></noscript>'
        f"</div>"
    )

    if needs_collapse:
        content_html = (
            f'<div class="expandable-markdown">'
            f'<div class="markdown-preview">'
            f"{rendered_html}"
            f"</div>"
            f'<div class="expand-control">'
            f'<button class="expand-btn">Show full output</button>'
            f"</div>"
            f"</div>"
        )
    else:
        # No collapse wrapper needed, but we keep the structure compatible
        content_html = rendered_html

    return (
        f'<div class="sub-agent-result-container">'
        f"{images_html}"
        f'<div class="sub-agent-toolbar">'
        f'<button type="button" class="raw-toggle" aria-pressed="false" title="Toggle raw text view">Raw</button>'
        f'<button type="button" class="copy-raw-btn" title="Copy raw content">Copy</button>'
        f"</div>"
        f'<div class="sub-agent-content">'
        f"{content_html}"
        f'<pre class="sub-agent-raw">{encoded}</pre>'
        f"</div>"
        f"</div>"
    )


def _render_text_block(text: str) -> str:
    lines = text.splitlines()
    encoded = _escape_html(text)
    content_html = f'<div style="white-space: pre-wrap; font-family: var(--font-mono);">{encoded}</div>'

    if len(lines) <= _TOOL_OUTPUT_PREVIEW_LINES:
        return content_html

    return (
        f'<div class="expandable-tool-output">'
        f'<div class="tool-output-preview">'
        f"{content_html}"
        f"</div>"
        f'<div class="expand-control">'
        f'<button class="expand-btn">Show full output</button>'
        f"</div>"
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
    ui_extra: model.ToolResultUIExtra | None, tool_call: message.ToolCallPart | None = None
) -> str | None:
    code = ""
    link: str | None = None
    line_count = 0

    if isinstance(ui_extra, model.MermaidLinkUIExtra):
        code = ui_extra.code
        link = ui_extra.link
        line_count = ui_extra.line_count

    if not code and tool_call and tool_call.tool_name == "Mermaid":
        try:
            args = json.loads(tool_call.arguments_json)
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
        return f'<div class="mermaid-container"><div class="mermaid">{escaped_code}</div>{toolbar_html}</div>'

    # Fallback to just link/toolbar if no code available (legacy support behavior)
    return toolbar_html


def _format_mermaid_tool_call(
    tool_call: message.ToolCallPart,
    result: message.ToolResultMessage | None,
    timestamp: datetime,
    mermaid_html: str,
    args_html: str,
    ts_str: str,
) -> str:
    # Build standard tool details but hidden
    should_collapse = _should_collapse(args_html)
    open_attr = "" if should_collapse else " open"

    details_html = (
        f'<div class="mermaid-meta" style="display: none;">'
        f'<div class="tool-header">'
        f'<span class="tool-name">{_escape_html(tool_call.tool_name)}</span>'
        f'<div class="tool-header-right">'
        f'<span class="tool-id">{_escape_html(tool_call.call_id)}</span>'
        f'<span class="timestamp">{ts_str}</span>'
        f"</div>"
        f"</div>"
        f'<details class="tool-args-collapsible"{open_attr}>'
        f"<summary>Arguments</summary>"
        f'<div class="tool-args-content">{args_html}</div>'
        f"</details>"
        f"</div>"
    )

    return (
        f'<div class="tool-call mermaid-tool-call">'
        f'<div class="mermaid-view">'
        f'<button class="mermaid-info-btn" title="Show/Hide Details">i</button>'
        f"{mermaid_html}"
        f"</div>"
        f"{details_html}"
        f"</div>"
    )


def _format_tool_call(
    tool_call: message.ToolCallPart,
    result: message.ToolResultMessage | None,
    timestamp: datetime,
) -> str:
    args_html = None
    is_todo_list = False
    ts_str = _format_msg_timestamp(timestamp)

    if tool_call.tool_name in ("TodoWrite", "update_plan"):
        args_html = _try_render_todo_args(tool_call.arguments_json, tool_call.tool_name)
        if args_html:
            is_todo_list = True

    if args_html is None:
        try:
            parsed = json.loads(tool_call.arguments_json)
            args_text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            args_text = tool_call.arguments_json

        args_html = _escape_html(args_text or "")

    if not args_html:
        args_html = '<span style="color: var(--text-dim); font-style: italic;">(no arguments)</span>'

    # Special handling for Mermaid
    if tool_call.tool_name == "Mermaid" and result:
        extras = _collect_ui_extras(result.ui_extra)
        mermaid_extra = next((x for x in extras if isinstance(x, model.MermaidLinkUIExtra)), None)
        mermaid_source = mermaid_extra if mermaid_extra else result.ui_extra
        mermaid_html = _get_mermaid_link_html(mermaid_source, tool_call)

        if mermaid_html:
            return _format_mermaid_tool_call(tool_call, result, timestamp, mermaid_html, args_html, ts_str)

    # Wrap tool-args with collapsible details element (except for TodoWrite which renders as a list)
    if is_todo_list:
        args_section = f'<div class="tool-args">{args_html}</div>'
    else:
        # Always collapse Mermaid, Edit, Write tools by default
        always_collapse_tools = {"Mermaid", "Edit", "Write"}
        force_collapse = tool_call.tool_name in always_collapse_tools

        # Collapse Memory tool for write operations
        if tool_call.tool_name == "Memory":
            try:
                parsed_args = json.loads(tool_call.arguments_json)
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
        f'<span class="tool-name">{_escape_html(tool_call.tool_name)}</span>',
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

        should_hide_text = tool_call.tool_name in ("TodoWrite", "update_plan") and result.status != "error"

        if (
            tool_call.tool_name == "Edit"
            and not any(isinstance(x, model.DiffUIExtra) for x in extras)
            and result.status != "error"
        ):
            try:
                args_data = json.loads(tool_call.arguments_json)
                file_path = args_data.get("file_path", "Unknown file")
                old_string = args_data.get("old_string", "")
                new_string = args_data.get("new_string", "")
                if old_string == "" and new_string:
                    extras.append(_build_add_only_diff(new_string, file_path))
            except (json.JSONDecodeError, TypeError):
                pass

        items_to_render: list[str] = []

        image_parts = _extract_image_parts(result.parts)
        for img in image_parts:
            if isinstance(img, message.ImageFilePart):
                items_to_render.append(_render_image_html(img.file_path))
            else:
                items_to_render.append(_render_image_url_html(img.url))

        if result.output_text and not should_hide_text:
            if is_sub_agent_tool(tool_call.tool_name):
                description = None
                try:
                    args = json.loads(tool_call.arguments_json)
                    if isinstance(args, dict):
                        typed_args = cast(dict[str, Any], args)
                        description = cast(str | None, typed_args.get("description"))
                except (json.JSONDecodeError, TypeError):
                    pass
                items_to_render.append(_render_sub_agent_result(result.output_text, description))
            else:
                items_to_render.append(_render_text_block(result.output_text))

        for extra in extras:
            if isinstance(extra, model.DiffUIExtra):
                items_to_render.append(_render_diff_block(extra))
            elif isinstance(extra, model.MarkdownDocUIExtra):
                items_to_render.append(_render_markdown_doc(extra))

        if mermaid_html:
            items_to_render.append(mermaid_html)

        if not items_to_render and not result.output_text and not should_hide_text:
            items_to_render.append('<div style="color: var(--text-dim); font-style: italic;">(empty output)</div>')

        if items_to_render:
            status_class = "success" if result.status == "success" else "error"
            html_parts.append(f'<div class="tool-result {status_class}">')
            html_parts.extend(items_to_render)
            html_parts.append("</div>")
    else:
        html_parts.append('<div class="tool-result pending">Executing...</div>')

    html_parts.append("</div>")
    return "".join(html_parts)


def _render_sub_agent_session(
    tool_result: message.ToolResultMessage,
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
    sub_tool_results = {item.call_id: item for item in sub_history if isinstance(item, message.ToolResultMessage)}

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
    tool_results = {item.call_id: item for item in history if isinstance(item, message.ToolResultMessage)}
    messages_html = _build_messages_html(history, tool_results)
    if not messages_html:
        messages_html = '<div class="text-dim p-4 italic">No messages recorded for this session yet.</div>'

    tools_html = _build_tools_html(tools)
    session_id = session.id
    session_updated = _format_timestamp(session.updated_at)
    work_dir = _shorten_path(str(session.work_dir))
    total_messages = len(
        [
            item
            for item in history
            if isinstance(item, message.Message) and not isinstance(item, message.ToolResultMessage)
        ]
    )
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
