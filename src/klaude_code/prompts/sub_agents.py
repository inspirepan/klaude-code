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
    "Correctness-focused code review agent that identifies real bugs in proposed changes.\n"
    "- Use for: Complex, multi-file changes with non-trivial logic that could harbor subtle bugs,\n"
    "  regressions, race conditions, security issues, data loss, or compatibility breaks\n"
    "- Don't use for: Style-only cleanup, simplification-only review, formatting checks, documentation\n"
    "  issues, or general code exploration\n"
    "- For non-trivial review requests, launch this in parallel with `code-maintenance-reviewer` and\n"
    "  synthesize the results yourself. For follow-up review after fixes, use only the reviewer whose\n"
    "  prior finding is being checked unless the user asks for another full review.\n"
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

MAINTENANCE_REVIEW_SUMMARY = (
    "Read-only code maintenance review agent that identifies cleanup, layering, efficiency, and\n"
    "project-convention issues in proposed changes.\n"
    "- Use for: Reuse opportunities, unnecessary complexity, redundant work, fragile altitude/layering,\n"
    "  and clear violations of governing CLAUDE.md/AGENTS.md instructions\n"
    "- Don't use for: Correctness/security regression hunting (use code-reviewer), direct edits,\n"
    "  formatting-only nits, or broad refactors outside the diff\n"
    "- For non-trivial review requests, launch this in parallel with `code-reviewer` and synthesize\n"
    "  the results yourself. Correctness findings from `code-reviewer` should outrank maintenance\n"
    "  findings when deciding what to report.\n"
    "- The prompt must include:\n"
    "  1. Background: what the user asked for and the intent behind the changes\n"
    "  2. Diff command: a shell command to view the changes (e.g. `git diff`, `git diff --cached`)\n"
    "  3. Key files: list the most important changed files and nearby helpers/modules\n"
    "  4. Focus (optional): cleanup, layering, efficiency, or convention concerns to prioritize\n"
    "- The agent reads surrounding context and governing instruction files autonomously and returns\n"
    "  structured read-only findings with priority levels.\n"
    "(Tools: Bash, Read)"
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
