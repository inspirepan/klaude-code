"""Sub-agent model-facing text: invoker summaries and fork-context identity prompts.

Centralizes text that appears in the Agent tool description or is injected
into sub-agent sessions.  Keep dependency-free.
"""

# ---------------------------------------------------------------------------
# Invoker summaries (shown under ``type:`` in the Agent tool description)
# ---------------------------------------------------------------------------

FINDER_SUMMARY = (
    "Searches the codebase by concept, or exhaustively by exact match (all call sites, all usages), and\n"
    "returns a short answer plus file paths (usually with line ranges) to Read -- the intermediate file dumps\n"
    "stay out of your context. Default choice for any codebase question beyond a known file or a single exact\n"
    "identifier. Launch several in one message when a task has several questions. Give each the research goal\n"
    "plus any keyword queries worth prioritizing.\n"
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
    "Adversarial correctness reviewer: starts from a fresh context with only the diff and assumes it is\n"
    "wrong until the code proves otherwise. Finds real bugs: regressions, race conditions, security issues,\n"
    "data loss, compatibility breaks. Returns findings with priority levels.\n"
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
    "Do NOT use the Agent tool to spawn sub-agents; search directly. "
    "Do NOT use the Rewind tool.\n\n"
)

FORK_CONTEXT_GENERAL_PROMPT = (
    "You are a newly spawned agent with the full conversation context "
    "from the parent session. Treat the next user message as your new task, "
    "and use the conversation history as background context. "
    "Do NOT use the Agent tool to spawn sub-agents: search directly, and leave reviewing your diff "
    "to the parent agent. "
    "Do NOT use the Rewind tool."
)
