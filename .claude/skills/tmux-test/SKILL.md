---
name: tmux-test
description: Test klaude-code interactively using tmux. Use when testing UI features, verifying changes, or debugging interactive behavior.
---

# tmux-test

Test klaude-code in a controlled tmux terminal environment.

## Quick Start

```bash
# Create tmux session with specific dimensions
tmux new-session -d -s test -x 120 -y 30

# Start klaude from source
tmux send-keys -t test 'uv run klaude' Enter

# Wait for startup, then capture output
sleep 3 && tmux capture-pane -t test -p

# Send input
tmux send-keys -t test 'your prompt here' Enter

# Send special keys
tmux send-keys -t test Escape
tmux send-keys -t test C-c  # ctrl+c

# Capture output after waiting
sleep 5 && tmux capture-pane -t test -p -S -50

# Cleanup
tmux kill-session -t test
```

## Key Points

- Use `-x` and `-y` to control terminal dimensions
- Use `sleep` to wait for startup or task completion
- Use `-S -N` with `capture-pane` to get N lines of scrollback history
- Use `-S -` with `capture-pane` for entire scrollback
- Use `tmux send-keys` with key names for special keys (Escape, C-c, Enter, etc.)
