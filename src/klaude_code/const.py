"""Centralized configuration constants for klaude_code.

This module consolidates all magic numbers and configuration values
that were previously scattered across the codebase.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


def _get_int_env(name: str, default: int) -> int:
    """Get an integer value from environment variable, or return default."""
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def get_system_temp() -> str:
    """Return system-level temp directory: /tmp on Unix, system temp on Windows."""
    if sys.platform == "win32":
        return tempfile.gettempdir()
    return "/tmp"


# =============================================================================
# Agent / LLM Configuration
# =============================================================================

MAX_FAILED_TURN_RETRIES = 10  # Maximum retry attempts for failed turns
RETRY_PRESERVE_PARTIAL_MESSAGE = True  # Preserve partial message on stream error for retry prefill
LLM_HTTP_TIMEOUT_TOTAL = 300.0  # HTTP timeout for LLM API requests (seconds)
LLM_HTTP_TIMEOUT_CONNECT = 15.0  # HTTP connect timeout (seconds)
LLM_HTTP_TIMEOUT_READ = 285.0  # HTTP read timeout (seconds)

ANTHROPIC_BETA_INTERLEAVED_THINKING = "interleaved-thinking-2025-05-14"  # Anthropic API beta flag
ANTHROPIC_BETA_OAUTH = "oauth-2025-04-20"  # Anthropic OAuth beta flag
ANTHROPIC_BETA_FINE_GRAINED_TOOL_STREAMING = "fine-grained-tool-streaming-2025-05-14"  # Anthropic streaming beta
CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."  # Claude identity string

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"  # OpenRouter API base URL

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"  # Codex API base URL
CODEX_USER_AGENT = "codex_cli_rs/0.0.0-klaude"  # Codex user agent string

SUPPORTED_IMAGE_SIZES = {"1K", "2K", "4K"}  # Supported image sizes for ImageGen tool

THROUGHPUT_MIN_DURATION_SEC = 0.15  # Minimum duration (seconds) for throughput calculation
INITIAL_RETRY_DELAY_S = 1.0  # Initial delay before retrying a failed turn (seconds)
MAX_RETRY_DELAY_S = 30.0  # Maximum delay between retries (seconds)
CANCEL_OUTPUT = "[Request interrupted by user for tool use]"  # Message shown when tool call is cancelled
EMPTY_TOOL_OUTPUT_MESSAGE = (
    "<system-reminder>Tool ran without output or errors</system-reminder>"  # Tool output placeholder
)
DEFAULT_MAX_TOKENS = 32000  # Default maximum tokens for LLM responses
DEFAULT_TEMPERATURE = 1.0  # Default temperature for LLM requests
DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS = 2048  # Default thinking budget tokens for Anthropic models


# =============================================================================
# Reminders
# =============================================================================

TODO_REMINDER_TOOL_CALL_THRESHOLD = 10  # Tool call count threshold for todo reminder
REMINDER_COOLDOWN_TURNS = 3  # Cooldown turns between reminder triggers


# =============================================================================
# Tool - Read
# =============================================================================

READ_CHAR_LIMIT_PER_LINE = 2000  # Maximum characters per line before truncation
READ_GLOBAL_LINE_CAP = _get_int_env("KLAUDE_READ_GLOBAL_LINE_CAP", 2000)  # Maximum lines to read from a file
READ_MAX_CHARS = _get_int_env("KLAUDE_READ_MAX_CHARS", 50000)  # Maximum total characters to read
READ_MAX_IMAGE_BYTES = _get_int_env("KLAUDE_READ_MAX_IMAGE_BYTES", 64 * 1024 * 1024)  # Max image size (64MB)
IMAGE_OUTPUT_MAX_BYTES = _get_int_env("KLAUDE_IMAGE_OUTPUT_MAX_BYTES", 64 * 1024 * 1024)  # Max decoded image (64MB)
BINARY_CHECK_SIZE = 8192  # Bytes to check for binary file detection


# =============================================================================
# Tool - Bash / Shell
# =============================================================================

BASH_DEFAULT_TIMEOUT_MS = 120000  # Default timeout for bash commands (milliseconds)
BASH_TERMINATE_TIMEOUT_SEC = 1.0  # Timeout before escalating to SIGKILL (seconds)
BASH_MODE_SESSION_OUTPUT_MAX_BYTES = 200 * 1024 * 1024  # Max command output captured for session history


# =============================================================================
# Tool - Web
# =============================================================================

WEB_FETCH_DEFAULT_TIMEOUT_SEC = 30  # Default timeout for web fetch requests (seconds)
WEB_FETCH_USER_AGENT = "Mozilla/5.0 (compatible; KlaudeCode/1.0)"  # User-Agent header for web requests
URL_FILENAME_MAX_LENGTH = 80  # Maximum length for extracting filename from URL
WEB_SEARCH_DEFAULT_MAX_RESULTS = 10  # Default number of search results
WEB_SEARCH_MAX_RESULTS_LIMIT = 20  # Maximum number of search results allowed
MERMAID_LIVE_PREFIX = "https://mermaid.live/view#pako:"  # Mermaid.live URL prefix


# =============================================================================
# Tool - Diff
# =============================================================================

DIFF_MAX_LINE_LENGTH_FOR_CHAR_DIFF = 2000  # Maximum line length for character-level diff
DIFF_DEFAULT_CONTEXT_LINES = 3  # Default number of context lines in diff output


# =============================================================================
# Tool - Output Truncation
# =============================================================================

TOOL_OUTPUT_MAX_LENGTH = 40000  # Maximum length for tool output before truncation
TOOL_OUTPUT_DISPLAY_HEAD = 10000  # Characters to show from the beginning of truncated output
TOOL_OUTPUT_DISPLAY_TAIL = 10000  # Characters to show from the end of truncated output
TOOL_OUTPUT_MAX_LINES = 2000  # Maximum lines for tool output before truncation
TOOL_OUTPUT_DISPLAY_HEAD_LINES = 1000  # Lines to show from the beginning of truncated output
TOOL_OUTPUT_DISPLAY_TAIL_LINES = 1000  # Lines to show from the end of truncated output
TOOL_OUTPUT_TRUNCATION_DIR = get_system_temp()  # Directory for saving full truncated output


# =============================================================================
# UI - Display
# =============================================================================

TAB_EXPAND_WIDTH = 8  # Tab expansion width for text rendering
DIFF_PREFIX_WIDTH = 4  # Width of line number prefix in diff display
MAX_DIFF_LINES = 500  # Maximum lines to show in diff output
INVALID_TOOL_CALL_MAX_LENGTH = 200  # Maximum length for invalid tool call display
TRUNCATE_DISPLAY_MAX_LINE_LENGTH = 500  # Maximum line length for truncated display
TRUNCATE_DISPLAY_MAX_LINES = 4  # Maximum lines for truncated display
MIN_HIDDEN_LINES_FOR_INDICATOR = 5  # Minimum hidden lines before showing truncation indicator
SUB_AGENT_RESULT_MAX_LINES = 10  # Maximum lines for sub-agent result display
TRUNCATE_HEAD_MAX_LINES = 2  # Maximum lines for sub-agent error display
BASH_OUTPUT_PANEL_THRESHOLD = 10  # Bash output line threshold for CodePanel display
BASH_MULTILINE_STRING_TRUNCATE_MAX_LINES = 4  # Max lines shown for heredoc / multiline string tokens in bash tool calls
URL_TRUNCATE_MAX_LENGTH = 400  # Maximum length for URL truncation in display
QUERY_DISPLAY_TRUNCATE_LENGTH = 80  # Maximum length for search query display
NOTIFY_COMPACT_LIMIT = 160  # Maximum length for notification body text


# =============================================================================
# UI - Markdown Streaming
# =============================================================================

UI_REFRESH_RATE_FPS = 10  # UI refresh rate (frames per second)
CROP_ABOVE_LIVE_REFRESH_PER_SECOND = 4.0  # CropAboveLive default refresh rate
MARKDOWN_STREAM_LIVE_REPAINT_ENABLED = True  # Enable live area for streaming markdown
MARKDOWN_STREAM_SYNCHRONIZED_OUTPUT_ENABLED = True  # Use terminal "Synchronized Output" to reduce flicker
STREAM_MAX_HEIGHT_SHRINK_RESET_LINES = 20  # Reset stream height ceiling after this shrinkage
MARKDOWN_LEFT_MARGIN = 0  # Left margin (columns) for markdown rendering
MARKDOWN_RIGHT_MARGIN = 0  # Right margin (columns) for markdown rendering


# =============================================================================
# UI - Spinner / Status
# =============================================================================

STATUS_HINT_TEXT = " (esc to interrupt)"  # Status hint text shown after spinner

# Spinner status texts
STATUS_WAITING_TEXT = "Loading …"
STATUS_THINKING_TEXT = "Thinking …"
STATUS_COMPOSING_TEXT = "Composing"
STATUS_COMPACTING_TEXT = "Compacting"
STATUS_RUNNING_TEXT = "Running …"

# Backwards-compatible alias for the default spinner status text.
STATUS_DEFAULT_TEXT = STATUS_WAITING_TEXT
SIGINT_DOUBLE_PRESS_EXIT_TEXT = "Press ctrl+c again to exit"  # Toast shown on first Ctrl+C during task waits
SPINNER_BREATH_PERIOD_SECONDS: float = 2.0  # Spinner breathing animation period (seconds)
STATUS_SHIMMER_PADDING = 10  # Horizontal padding for shimmer band position
STATUS_SHIMMER_BAND_HALF_WIDTH = 5.0  # Half-width of shimmer band in characters
STATUS_SHIMMER_ALPHA_SCALE = 0.7  # Scale factor for shimmer intensity
STATUS_SHOW_BUFFER_LENGTH = False  # Show character count (e.g., "(213)") during text generation


# =============================================================================
# UI - Completion System
# =============================================================================

COMPLETER_DEBOUNCE_SEC = 0.25  # Debounce time for file path completion (seconds)
COMPLETER_CACHE_TTL_SEC = 60.0  # Cache TTL for completion results (seconds)
COMPLETER_CMD_TIMEOUT_SEC = 3.0  # Timeout for completion subprocess commands (seconds)


# =============================================================================
# Debug / Logging
# =============================================================================

DEFAULT_DEBUG_LOG_DIR = Path.home() / ".klaude" / "logs"  # Default debug log directory
DEFAULT_DEBUG_LOG_FILE = DEFAULT_DEBUG_LOG_DIR / "debug.log"  # Default debug log file path
LOG_MAX_BYTES = 10 * 1024 * 1024  # Maximum log file size before rotation (10MB)
LOG_BACKUP_COUNT = 3  # Number of backup log files to keep


# =============================================================================
# Project Paths
# =============================================================================


def project_key_from_cwd() -> str:
    """Derive the project key from the current working directory."""
    return str(Path.cwd()).strip("/").replace("/", "-")


@dataclass(frozen=True)
class ProjectPaths:
    """Path utilities for project-scoped storage."""

    project_key: str

    @property
    def base_dir(self) -> Path:
        return Path.home() / ".klaude" / "projects" / self.project_key

    @property
    def sessions_dir(self) -> Path:
        return self.base_dir / "sessions"

    @property
    def exports_dir(self) -> Path:
        return self.base_dir / "exports"

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def images_dir(self, session_id: str) -> Path:
        """Return the directory for storing session-scoped image artifacts."""
        return self.session_dir(session_id) / "images"

    def events_file(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "events.jsonl"

    def meta_file(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "meta.json"
