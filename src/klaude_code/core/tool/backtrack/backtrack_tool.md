Revert conversation history to a previous checkpoint, discarding everything after it.

Use this tool when:
- You spent many tokens on exploration that turned out unproductive
- You read large files but only need to keep key information
- A deep debugging session can be summarized before continuing
- The current approach is stuck and you want to try a different path

The note you provide will be shown to your future self at the checkpoint, so include:
- Key findings from your exploration
- What approaches did not work and why
- Important context needed to continue

IMPORTANT:
- File system changes are NOT reverted - only conversation history is affected
- Checkpoints are created automatically at the start of each turn
- Available checkpoints appear as <system>Checkpoint N</system> in the conversation
