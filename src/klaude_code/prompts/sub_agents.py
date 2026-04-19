"""Sub-agent model-facing text: invoker summaries and fork-context identity prompts.

Centralizes text that appears in the Agent tool description or is injected
into sub-agent sessions.  Keep dependency-free.
"""

# ---------------------------------------------------------------------------
# Invoker summaries (shown under ``type:`` in the Agent tool description)
# ---------------------------------------------------------------------------

FINDER_SUMMARY = (
    "Intelligently search your codebase: use it for complex, multi-step search tasks where you\n"
    "need to find code based on functionality or concepts rather than exact matches. Anytime you\n"
    "want to chain multiple grep calls you should use this tool.\n"
    "Always spawn multiple search agents in parallel to maximise speed.\n"
    "The prompt must include:\n"
    "- objective: a natural-language description of the broader task or research goal\n"
    "- search_queries: keyword queries to prioritize specific term matches\n"
    "(Tools: Bash, Read)"
)

GENERAL_PURPOSE_SUMMARY = (
    "Fire-and-forget executor for heavy, multi-file implementations. Think of it as a productive\n"
    "junior engineer who can't ask follow-ups once started.\n"
    "- Use for: Feature scaffolding, cross-layer refactors, mass migrations, boilerplate generation\n"
    "- Don't use for: Read-only research or search (use finder instead), architectural decisions\n"
    "- Prompt it with detailed instructions on the goal, enumerate the deliverables, give it step\n"
    "  by step procedures and ways to validate the results. Also give it constraints (e.g. coding\n"
    "  style) and include relevant context snippets or examples. (Tools: All Tools)"
)

FORK_CONTEXT_SUMMARY = (
    "Same as general-purpose but with full conversation history forked from the parent agent.\n"
    "Use when the sub-agent needs awareness of what happened earlier in the session.\n"
    "- Use for: Session-aware tasks like updating project docs, summarizing session learnings,\n"
    "  or any task that requires the full conversation context to do well\n"
    "- Don't use for: Standalone tasks that don't need session history (use general-purpose instead)\n"
    "(Tools: inherited from parent)"
)

REVIEW_SUMMARY = (
    "Code review agent that identifies real bugs in proposed changes.\n"
    "- Use for: Complex, multi-file changes with non-trivial logic that could harbor subtle bugs\n"
    "- Don't use for: Small/simple changes (single-file edits, config tweaks, renames, typo fixes, "
    "straightforward bug fixes), style/formatting checks, or general code exploration\n"
    "- IMPORTANT: Only invoke review ONCE per task. After fixing issues found by a review, do NOT\n"
    "  launch another review to verify the fixes -- apply your own judgement instead. A second\n"
    "  review is only warranted if the user explicitly asks for one.\n"
    "- The prompt must include:\n"
    "  1. Background: what the user asked for, the intent behind the changes, key decisions and tradeoffs made\n"
    "  2. Diff command: a shell command to view the changes (e.g. `git diff`, `git diff --cached`)\n"
    "  3. Key files: list the most important files changed and any related files for context\n"
    "  4. Focus (optional): specific concerns or areas to pay extra attention to\n"
    "- For follow-up reviews (after fixing issues from a prior review): include the previous\n"
    "  findings in the prompt and scope the diff command to only the fix commits, so the agent\n"
    "  can verify fixes incrementally instead of re-reviewing the entire changeset.\n"
    "- The agent reads surrounding context autonomously and returns structured findings\n"
    "  with priority levels.\n"
    "(Tools: Bash, Read)"
)

SIMPLIFIER_SUMMARY = (
    "Code simplification agent that refines recently changed code for clarity and consistency.\n"
    "- Use for: Cleaning up code after implementation -- reducing nesting, eliminating redundancy,\n"
    "  improving naming, and aligning with project conventions\n"
    "- Don't use for: Bug fixing, feature changes, architecture decisions, or style-only formatting\n"
    "- The prompt must include:\n"
    "  1. Diff command: a shell command to view the recent changes (e.g. `git diff`, `git diff HEAD~1`)\n"
    "  2. Scope (optional): specific files or areas to focus on\n"
    "  3. Constraints (optional): project conventions or patterns to preserve\n"
    "- The agent reads project conventions autonomously, applies targeted simplifications,\n"
    "  and reports what was changed and why.\n"
    "(Tools: Bash, Read, Edit)"
)

# ---------------------------------------------------------------------------
# Fork-context identity prompts (injected into forked sub-agent sessions)
# ---------------------------------------------------------------------------

FORK_CONTEXT_WITH_ROLE_PROMPT = (
    "You are no longer the main coding agent. "
    "You are now acting as a specialized sub-agent. "
    "The conversation history above was forked from the parent session "
    "-- use it as background context only. "
    "Do NOT use the Agent tool to spawn sub-agents. "
    "Do NOT use the Rewind tool.\n\n"
)

FORK_CONTEXT_GENERAL_PROMPT = (
    "You are a newly spawned agent with the full conversation context "
    "from the parent session. Treat the next user message as your new task, "
    "and use the conversation history as background context. "
    "Do NOT use the Agent tool to spawn sub-agents. "
    "Do NOT use the Rewind tool."
)
