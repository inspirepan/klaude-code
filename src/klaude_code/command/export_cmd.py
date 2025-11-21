from __future__ import annotations

import html
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Final

from klaude_code.command.command_abc import CommandABC, CommandResult
from klaude_code.command.registry import register_command
from klaude_code.core import Agent
from klaude_code.protocol.commands import CommandName
from klaude_code.protocol.events import DeveloperMessageEvent
from klaude_code.protocol.model import (
    AssistantMessageItem,
    CommandOutput,
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


@register_command
class ExportCommand(CommandABC):
    """Export the current session into a standalone HTML transcript."""

    @property
    def name(self) -> CommandName:
        return CommandName.EXPORT

    @property
    def summary(self) -> str:
        return "Export current session to HTML"

    @property
    def support_addition_params(self) -> bool:
        return True

    @property
    def is_interactive(self) -> bool:
        return False

    async def run(self, raw: str, agent: Agent) -> CommandResult:
        try:
            output_path = self._resolve_output_path(raw, agent)
            html_doc = self._build_html(agent)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html_doc, encoding="utf-8")
            self._open_file(output_path)
            return CommandResult(
                events=[
                    DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=DeveloperMessageItem(
                            content=f"Session exported and opened: {output_path}",
                            command_output=CommandOutput(command_name=self.name),
                        ),
                    )
                ]
            )
        except Exception as exc:  # pragma: no cover - safeguard for unexpected errors
            return CommandResult(
                events=[
                    DeveloperMessageEvent(
                        session_id=agent.session.id,
                        item=DeveloperMessageItem(
                            content=f"Failed to export session: {exc}",
                            command_output=CommandOutput(command_name=self.name, is_error=True),
                        ),
                    )
                ]
            )

    def _resolve_output_path(self, raw: str, agent: Agent) -> Path:
        trimmed = raw.strip()
        if trimmed:
            candidate = Path(trimmed).expanduser()
            if not candidate.is_absolute():
                candidate = Path(agent.session.work_dir) / candidate
            if candidate.suffix.lower() != ".html":
                candidate = candidate.with_suffix(".html")
            return candidate
        session_messages_file = agent.session._messages_file()  # type: ignore[reportPrivateUsage]
        default_path = session_messages_file.with_suffix(".html")
        return default_path

    def _open_file(self, path: Path) -> None:
        try:
            subprocess.run(["open", str(path)], check=True)
        except FileNotFoundError as exc:  # pragma: no cover - depends on platform
            msg = "`open` command not found; please open the HTML manually."
            raise RuntimeError(msg) from exc
        except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on platform
            msg = f"Failed to open HTML with `open`: {exc}"
            raise RuntimeError(msg) from exc

    def _build_html(self, agent: Agent) -> str:
        session = agent.session
        history = session.conversation_history
        tool_results = {item.call_id: item for item in history if isinstance(item, ToolResultItem)}
        messages_html = self._build_messages_html(history, tool_results)
        if not messages_html:
            messages_html = '<div class="text-dim p-4 italic">No messages recorded for this session yet.</div>'

        system_prompt = session.system_prompt or ""
        tools_html = self._build_tools_html(agent)
        session_id = session.id
        session_updated = self._format_timestamp(session.updated_at)
        work_dir = self._shorten_path(str(session.work_dir))
        model_name = session.model_name or agent.llm_clients.main.model_name
        total_messages = len([item for item in history if not isinstance(item, ToolResultItem)])
        footer_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Session Export - {self._escape_html(session_id)}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-body: {COLORS["bodyBg"]};
            --bg-container: {COLORS["containerBg"]};
            --bg-card: {COLORS["cardBg"]};
            --border: {COLORS["borderColor"]};
            --text: {COLORS["text"]};
            --text-dim: {COLORS["textDim"]};
            --accent: {COLORS["cyan"]};
            --accent-dim: rgba(34, 211, 238, 0.1);
            --success: {COLORS["green"]};
            --error: {COLORS["red"]};
            --font-sans: 'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
            --font-mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', Consolas, monospace;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            background-color: var(--bg-body);
            color: var(--text);
            font-family: var(--font-sans);
            line-height: 1.6;
            font-size: 15px;
            -webkit-font-smoothing: antialiased;
        }}

        .container {{
            max-width: 960px;
            margin: 0 auto;
            padding: 20px;
        }}

        /* Header */
        .header {{
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }}

        .header h1 {{
            font-size: 20px;
            font-weight: 700;
            margin-bottom: 16px;
            background: linear-gradient(to right, var(--accent), #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: inline-block;
        }}

        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }}

        .meta-item {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}

        .meta-label {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-dim);
        }}

        .meta-value {{
            font-family: var(--font-mono);
            font-size: 13px;
            color: var(--text);
        }}

        /* Components */
        details {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            margin-bottom: 12px;
            overflow: hidden;
        }}

        summary {{
            padding: 8px 14px;
            font-weight: 600;
            cursor: pointer;
            user-select: none;
            background: rgba(255,255,255,0.02);
            transition: background 0.2s;
            list-style: none;
            display: flex;
            align-items: center;
            gap: 8px;
            min-height: 34px;
            line-height: 1.2;
        }}
        
        summary::-webkit-details-marker {{ display: none; }}
        summary::before {{
            content: "▶";
            font-size: 10px;
            transition: transform 0.2s;
            display: inline-flex;
            align-items: center;
        }}
        details[open] summary::before {{
            transform: rotate(90deg);
        }}

        summary:hover {{ background: rgba(255,255,255,0.04); }}

        .details-content {{
            padding: 16px;
            border-top: 1px solid var(--border);
            font-size: 14px;
            color: var(--text-dim);
            background: var(--bg-body);
            overflow-x: auto;
        }}

        /* Messages */
        .message-stream {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}

        .message-group {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}

        .role-label {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
            color: var(--text-dim);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        summary.role-label {{ margin-bottom: 0; }}
        
        .role-label.user {{ color: var(--accent); }}
        .role-label.assistant {{ color: var(--success); }}

        .message-content {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 12px;
            box-shadow: 0 2px 4px -1px rgba(0, 0, 0, 0.1);
            font-size: 13px;
        }}
        .assistant-message {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        .assistant-toolbar {{
            display: flex;
            justify-content: flex-end;
            align-items: center;
        }}
        .raw-toggle {{
            border: 1px solid var(--border);
            background: transparent;
            color: var(--text-dim);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            padding: 2px 10px;
            border-radius: 999px;
            cursor: pointer;
            transition: color 0.2s, border-color 0.2s, background 0.2s;
            font-weight: 600;
        }}
        .raw-toggle:hover {{
            color: var(--text);
            border-color: var(--accent);
        }}
        .raw-toggle.active {{
            color: var(--accent);
            border-color: var(--accent);
            background: rgba(34, 211, 238, 0.08);
        }}
        .assistant-rendered {{
            width: 100%;
        }}
        .assistant-raw {{
            display: none;
            font-family: var(--font-mono);
            font-size: 13px;
            white-space: pre-wrap;
            background: rgba(255,255,255,0.02);
            border: 1px dashed var(--border);
            border-radius: 4px;
            padding: 12px;
        }}
        .assistant-message.show-raw .assistant-rendered {{ display: none; }}
        .assistant-message.show-raw .assistant-raw {{ display: block; }}
        
        .message-content.user {{
            background: rgba(39, 39, 42, 0.5);
            border-left: 3px solid var(--accent);
        }}

        .thinking-block {{
            margin-top: 8px;
            padding: 12px 16px;
            border-left: 2px solid var(--border);
            color: var(--text-dim);
            font-style: italic;
            font-size: 13px;
            background: rgba(255,255,255,0.02);
        }}

        /* Tool Calls */
        .tool-call {{
            margin-top: 16px;
            border: 1px solid var(--border);
            border-radius: 6px;
            overflow: hidden;
            font-size: 13px;
        }}
        
        .tool-header {{
            padding: 8px 12px;
            background: var(--bg-container);
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-family: var(--font-mono);
        }}
        
        .tool-name {{ font-weight: 600; color: var(--accent); }}
        .tool-id {{ color: var(--text-dim); font-size: 11px; }}

        .tool-args {{
            padding: 12px;
            background: var(--bg-body);
            font-family: var(--font-mono);
            color: var(--text-dim);
            overflow-x: auto;
            white-space: pre-wrap;
        }}

        .tool-result {{
            border-top: 1px solid var(--border);
            padding: 12px;
        }}
        
        .tool-result.success {{ background: rgba(74, 222, 128, 0.05); color: var(--text); }}
        .tool-result.error {{ background: rgba(248, 113, 113, 0.05); color: var(--error); }}
        .tool-result.pending {{ background: rgba(255, 255, 255, 0.02); color: var(--text-dim); }}

        /* Markdown Elements */
        .markdown-body {{ font-family: var(--font-sans); }}
        .markdown-body hr {{
            height: 0;
            margin: 24px 0;
            border: none;
            border-top: 1px solid var(--border);
        }}
        .markdown-body pre {{
            background: #111;
            padding: 16px;
            border-radius: 6px;
            overflow-x: auto;
            margin: 12px 0;
            border: 1px solid var(--border);
        }}
        .markdown-body code {{
            font-family: var(--font-mono);
            font-size: 0.9em;
            background: rgba(255,255,255,0.1);
            padding: 2px 4px;
            border-radius: 4px;
        }}
        .markdown-body p {{ margin-bottom: 12px; }}
        .markdown-body ul, .markdown-body ol {{
            margin-bottom: 12px;
            padding-left: 1.5rem;
            list-style-position: outside;
        }}
        .markdown-body ul ul,
        .markdown-body ol ul,
        .markdown-body ul ol,
        .markdown-body ol ol {{
            margin-left: 1rem;
        }}
        
        /* Diff View */
        .diff-view {{
            font-family: var(--font-mono);
            background: #111;
            padding: 12px;
            border-radius: 6px;
            overflow-x: auto;
        }}
        .diff-line {{ white-space: pre; }}
        .diff-plus {{ color: var(--success); background: rgba(74, 222, 128, 0.1); display: block; }}
        .diff-minus {{ color: var(--error); background: rgba(248, 113, 113, 0.1); display: block; }}
        .diff-ctx {{ color: var(--text-dim); opacity: 0.6; display: block; }}

        .footer {{
            margin-top: 60px;
            text-align: center;
            color: var(--text-dim);
            font-size: 12px;
            border-top: 1px solid var(--border);
            padding-top: 24px;
        }}
        
        .expandable {{ cursor: pointer; }}
        .expandable .full-text {{ display: none; }}
        .expandable.expanded .preview-text {{ display: none; }}
        .expandable.expanded .full-text {{ display: block; }}
        .expand-hint {{ font-size: 11px; color: var(--accent); font-style: italic; margin-top: 4px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Session Export</h1>
            <div class="meta-grid">
                <div class="meta-item">
                    <span class="meta-label">Session ID</span>
                    <span class="meta-value">{self._escape_html(session_id)}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Model</span>
                    <span class="meta-value">{self._escape_html(model_name)}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Updated</span>
                    <span class="meta-value">{self._escape_html(session_updated)}</span>
                </div>
                <div class="meta-item">
                    <span class="meta-label">Directory</span>
                    <span class="meta-value" title="{self._escape_html(str(session.work_dir))}">{self._escape_html(work_dir)}</span>
                </div>
            </div>
        </div>

        <details>
            <summary>System Prompt</summary>
            <div class="details-content system-prompt-content" style="font-family: var(--font-mono); white-space: pre-wrap;">{self._escape_html(system_prompt)}</div>
        </details>

        <details>
            <summary>Available Tools</summary>
            <div class="details-content">
                {tools_html}
            </div>
        </details>

        <div class="message-stream">
            {messages_html}
        </div>

        <div class="footer">
            Generated by klaude-code • {self._escape_html(footer_time)} • {total_messages} messages
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
        // Markdown rendering
        document.querySelectorAll('.markdown-content').forEach((el) => {{
            const raw = el.dataset.raw;
            if (raw && window.marked) {{
                el.innerHTML = window.marked.parse(raw);
            }}
        }});

        // Expandable tool outputs
        document.querySelectorAll('.expandable').forEach(el => {{
            el.addEventListener('click', () => {{
                el.classList.toggle('expanded');
            }});
        }});

        // Assistant raw toggle
        document.querySelectorAll('.assistant-message').forEach(block => {{
            const toggle = block.querySelector('.raw-toggle');
            const rendered = block.querySelector('.assistant-rendered');
            const raw = block.querySelector('.assistant-raw');
            if (!toggle || !rendered || !raw) {{
                return;
            }}

            const setState = (showRaw) => {{
                block.classList.toggle('show-raw', showRaw);
                toggle.classList.toggle('active', showRaw);
                toggle.setAttribute('aria-pressed', String(showRaw));
                toggle.textContent = showRaw ? 'Markdown' : 'Raw';
            }};

            toggle.addEventListener('click', event => {{
                event.stopPropagation();
                const nextState = !block.classList.contains('show-raw');
                setState(nextState);
            }});
        }});
    </script>
</body>
</html>"""

    def _build_tools_html(self, agent: Agent) -> str:
        tools = agent.tools or []
        if not tools:
            return '<div style="padding: 12px; font-style: italic;">No tools registered for this session.</div>'
        chunks: list[str] = []
        for tool in tools:
            name = self._escape_html(tool.name)
            description = self._escape_html(tool.description)
            chunks.append(
                f'<div style="margin-bottom: 8px; font-family: var(--font-mono);"><strong style="color: var(--text);">{name}</strong> <span style="color: var(--text-dim);">- {description}</span></div>'
            )
        return "".join(chunks)

    def _build_messages_html(
        self,
        history: list[ConversationItem],
        tool_results: dict[str, ToolResultItem],
    ) -> str:
        blocks: list[str] = []
        assistant_counter = 0

        for item in history:
            if isinstance(item, ToolResultItem):
                continue

            if isinstance(item, UserMessageItem):
                text = self._escape_html(item.content or "")
                blocks.append(
                    f'<div class="message-group">'
                    f'<div class="role-label user">User</div>'
                    f'<div class="message-content user" style="white-space: pre-wrap;">{text}</div>'
                    f"</div>"
                )
            elif isinstance(item, ReasoningTextItem):
                text = self._escape_html(item.content)
                blocks.append(f'<div class="thinking-block">{text.replace("\n", "<br>")}</div>')
            elif isinstance(item, ReasoningEncryptedItem):
                pass
            elif isinstance(item, AssistantMessageItem):
                assistant_counter += 1
                blocks.append(self._render_assistant_message(assistant_counter, item.content or ""))
            elif isinstance(item, DeveloperMessageItem):
                content = self._escape_html(item.content or "")
                blocks.append(
                    f"<details>"
                    f'<summary class="role-label">Developer</summary>'
                    f'<div class="details-content message-content" style="border-left: 3px solid var(--accent); white-space: pre-wrap;">{content}</div>'
                    f"</details>"
                )
            elif isinstance(item, ToolCallItem):
                result = tool_results.get(item.call_id)
                blocks.append(self._format_tool_call(item, result))

        return "\n".join(blocks)

    def _render_assistant_message(self, index: int, content: str) -> str:
        encoded = self._escape_html(content)
        return (
            f'<div class="message-group">'
            f'<div class="role-label assistant">Assistant</div>'
            f'<div class="message-content assistant-message">'
            f'<div class="assistant-toolbar">'
            f'<button type="button" class="raw-toggle" aria-pressed="false" title="Toggle raw text view">Raw</button>'
            f"</div>"
            f'<div class="assistant-rendered markdown-content markdown-body" data-raw="{encoded}">'
            f'<noscript><pre style="white-space: pre-wrap;">{encoded}</pre></noscript>'
            f"</div>"
            f'<pre class="assistant-raw">{encoded}</pre>'
            f"</div>"
            f"</div>"
        )

    def _format_tool_call(self, tool_call: ToolCallItem, result: ToolResultItem | None) -> str:
        try:
            parsed = json.loads(tool_call.arguments)
            args_text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception:
            args_text = tool_call.arguments

        args_html = self._escape_html(args_text or "")
        if not args_html:
            args_html = '<span style="color: var(--text-dim); font-style: italic;">(no arguments)</span>'

        # Construct the tool call block
        html_parts = [
            '<div class="tool-call">',
            '<div class="tool-header">',
            f'<span class="tool-name">{self._escape_html(tool_call.name)}</span>',
            f'<span class="tool-id">{self._escape_html(tool_call.call_id)}</span>',
            "</div>",
            f'<div class="tool-args">{args_html}</div>',
        ]

        if result:
            # Determine result status class
            status_class = result.status if result.status in ("success", "error") else "success"
            html_parts.append(f'<div class="tool-result {status_class}">')

            if result.output:
                html_parts.append(self._render_text_block(result.output))

            diff_text = self._get_diff_text(result.ui_extra)
            if diff_text:
                html_parts.append(self._render_diff_block(diff_text))

            if not result.output and not diff_text:
                html_parts.append('<div style="color: var(--text-dim); font-style: italic;">(empty output)</div>')

            html_parts.append("</div>")
        else:
            html_parts.append('<div class="tool-result pending">Executing...</div>')

        html_parts.append("</div>")
        return "".join(html_parts)

    def _render_text_block(self, text: str) -> str:
        lines = text.splitlines()
        escaped_lines = [self._escape_html(line) for line in lines]

        if len(lines) <= _TOOL_OUTPUT_PREVIEW_LINES:
            content = "\n".join(escaped_lines)
            return (
                f'<div style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 13px;">{content}</div>'
            )

        preview = "\n".join(escaped_lines[:_TOOL_OUTPUT_PREVIEW_LINES])
        full = "\n".join(escaped_lines)

        return (
            f'<div class="expandable-output expandable">'
            f'<div class="preview-text" style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 13px;">{preview}</div>'
            f'<div class="full-text" style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 13px;">{full}</div>'
            f'<div class="expand-hint expand-text">Click to expand full output ({len(lines)} lines)</div>'
            f"</div>"
        )

    def _render_diff_block(self, diff: str) -> str:
        lines = diff.splitlines()
        rendered: list[str] = []
        for line in lines:
            escaped = self._escape_html(line)
            if line.startswith("+"):
                rendered.append(f'<span class="diff-line diff-plus">{escaped}</span>')
            elif line.startswith("-"):
                rendered.append(f'<span class="diff-line diff-minus">{escaped}</span>')
            else:
                rendered.append(f'<span class="diff-line diff-ctx">{escaped}</span>')
        return f'<div class="diff-view">{"".join(rendered)}</div>'

    def _escape_html(self, text: str) -> str:
        return html.escape(text, quote=True).replace("'", "&#39;")

    def _shorten_path(self, path: str) -> str:
        home = str(Path.home())
        if path.startswith(home):
            return path.replace(home, "~", 1)
        return path

    def _format_timestamp(self, value: float | None) -> str:
        if not value or value <= 0:
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    def _get_diff_text(self, ui_extra: ToolResultUIExtra | None) -> str | None:
        if ui_extra is None:
            return None
        if ui_extra.type != ToolResultUIExtraType.DIFF_TEXT:
            return None
        return ui_extra.diff_text
