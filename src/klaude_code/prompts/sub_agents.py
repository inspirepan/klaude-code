"""Sub-agent model-facing text: invoker summaries and fork-context identity prompts.

Centralizes text that appears in the Agent tool description or is injected
into sub-agent sessions.  Keep dependency-free.
"""

# ---------------------------------------------------------------------------
# Invoker summaries (shown under ``type:`` in the Agent tool description)
# ---------------------------------------------------------------------------

FINDER_SUMMARY = (
    "Searches the codebase by functionality or concept rather than exact match, and returns only the\n"
    "conclusion -- the intermediate file dumps stay out of your context. Default choice for any search\n"
    "beyond a single known-target lookup. Give it the research goal plus any keyword queries worth\n"
    "prioritizing.\n"
    "(Tools: Bash, Read)"
)

GENERAL_PURPOSE_SUMMARY = (
    "Fire-and-forget executor for heavy, multi-file implementation: feature scaffolding, cross-layer\n"
    "refactors, mass migrations, boilerplate. It cannot ask follow-ups once started, so the prompt\n"
    "must carry the goal, the deliverables, the constraints to respect, and how to validate the work.\n"
    "(Tools: All Tools)"
)

FORK_CONTEXT_SUMMARY = (
    "Same as general-purpose, but forks the parent's full conversation history. Use when the task\n"
    "needs to know what happened earlier in the session -- updating project docs, summarizing what\n"
    "was learned, and similar.\n"
    "(Tools: inherited from parent)"
)

REVIEW_SUMMARY = (
    "Finds real bugs in proposed changes: regressions, race conditions, security issues, data loss,\n"
    "compatibility breaks. Use it on complex or multi-file changes whose logic could hide a subtle\n"
    "failure. Returns findings with priority levels.\n"
    "(Tools: Bash, Read)"
)

MAINTENANCE_REVIEW_SUMMARY = (
    "Reviews proposed changes for maintainability: missed reuse, unnecessary complexity, wasted work,\n"
    "fragile layering, and violations of governing CLAUDE.md/AGENTS.md rules. Bugs are `code-reviewer`'s\n"
    "job, not this one's. Read-only; returns findings with priority levels.\n"
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
