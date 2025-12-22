"""Centralized configuration constants for klaude_code.

This module consolidates all magic numbers and configuration values
that were previously scattered across the codebase.
"""

from pathlib import Path

# =============================================================================
# Agent Configuration
# =============================================================================

# Timeout for waiting for the first event from LLM (seconds)
FIRST_EVENT_TIMEOUT_S = 200.0

# Maximum number of retry attempts for failed turns
MAX_FAILED_TURN_RETRIES = 10

# Initial delay before retrying a failed turn (seconds)
INITIAL_RETRY_DELAY_S = 1.0

# Maximum delay between retries (seconds)
MAX_RETRY_DELAY_S = 30.0

# Message shown when a tool call is cancelled by the user
CANCEL_OUTPUT = "[Request interrupted by user for tool use]"

# Default maximum tokens for LLM responses
DEFAULT_MAX_TOKENS = 32000

# Default temperature for LLM requests
DEFAULT_TEMPERATURE = 1.0

# Default thinking budget tokens for Anthropic models
DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS = 2048

# Tool call count threshold for todo reminder
TODO_REMINDER_TOOL_CALL_THRESHOLD = 10


# =============================================================================
# Tool
# =============================================================================

# -- Read Tool --
# Maximum characters per line before truncation
READ_CHAR_LIMIT_PER_LINE = 2000

# Maximum number of lines to read from a file
READ_GLOBAL_LINE_CAP = 2000

# Maximum total characters to read (truncates beyond this limit)
READ_MAX_CHARS = 50000

# Maximum image file size in bytes (4MB)
READ_MAX_IMAGE_BYTES = 4 * 1024 * 1024

# -- Bash Tool --
# Default timeout for bash commands (milliseconds)
BASH_DEFAULT_TIMEOUT_MS = 120000

# -- Tool Output --
# Maximum length for tool output before truncation
TOOL_OUTPUT_MAX_LENGTH = 40000

# Characters to show from the beginning of truncated output
TOOL_OUTPUT_DISPLAY_HEAD = 10000

# Characters to show from the end of truncated output
TOOL_OUTPUT_DISPLAY_TAIL = 10000

# Directory for saving full truncated output
TOOL_OUTPUT_TRUNCATION_DIR = "/tmp/klaude"


# =============================================================================
# UI
# =============================================================================

# Width of line number prefix in diff display
DIFF_PREFIX_WIDTH = 4

# Maximum lines to show in diff output
MAX_DIFF_LINES = 1000

# Maximum length for invalid tool call display
INVALID_TOOL_CALL_MAX_LENGTH = 500

# Maximum line length for truncated display output
TRUNCATE_DISPLAY_MAX_LINE_LENGTH = 1000

# Maximum lines for truncated display output
TRUNCATE_DISPLAY_MAX_LINES = 8

# Maximum lines for sub-agent result display
SUB_AGENT_RESULT_MAX_LINES = 50


# UI refresh rate (frames per second) for debounced content streaming
UI_REFRESH_RATE_FPS = 10

# Enable live area for streaming markdown (shows incomplete blocks being typed)
# When False, only completed markdown blocks are displayed (more stable, less flicker)
MARKDOWN_STREAM_LIVE_REPAINT_ENABLED = False

# Number of lines to keep visible at bottom of markdown streaming window
MARKDOWN_STREAM_LIVE_WINDOW = 6

# Left margin (columns) to reserve when rendering markdown
MARKDOWN_LEFT_MARGIN = 2

# Right margin (columns) to reserve when rendering markdown
MARKDOWN_RIGHT_MARGIN = 2

# Status hint text shown after spinner status
STATUS_HINT_TEXT = " (esc to interrupt)"

# Default spinner status text when idle/thinking
STATUS_DEFAULT_TEXT = "Thinking …"

# Status shimmer animation
# Horizontal padding used when computing shimmer band position
STATUS_SHIMMER_PADDING = 10
# Half-width of the shimmer band in characters
STATUS_SHIMMER_BAND_HALF_WIDTH = 5.0
# Scale factor applied to shimmer intensity when blending colors
STATUS_SHIMMER_ALPHA_SCALE = 0.7

# Spinner breathing and shimmer animation period
# Duration in seconds for one full breathe-in + breathe-out cycle (breathing)
# and one full shimmer sweep across the text (shimmer)
SPINNER_BREATH_PERIOD_SECONDS: float = 2.0


# =============================================================================
# Debug / Logging
# =============================================================================

# Default debug log directory (user cache)
DEFAULT_DEBUG_LOG_DIR = Path.home() / ".klaude" / "logs"

# Default debug log file path (symlink to latest session)
DEFAULT_DEBUG_LOG_FILE = DEFAULT_DEBUG_LOG_DIR / "debug.log"

# Maximum log file size before rotation (10MB)
LOG_MAX_BYTES = 10 * 1024 * 1024

# Number of backup log files to keep
LOG_BACKUP_COUNT = 3
