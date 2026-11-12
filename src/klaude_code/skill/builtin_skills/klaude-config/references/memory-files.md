---
name: memory-files
description: CLAUDE.md, AGENTS.md, and auto memory file locations, discovery rules, and limits
---

# Memory Files Reference

Memory files provide persistent instructions attached to conversation context as developer-message reminders.

## File Names

Each directory contributes only the first existing file in this order: `AGENTS.md`, `CLAUDE.md`, `AGENT.md`.

## Discovery Locations

### User-level (global, all projects)

These directories are checked for memory files:
- `~/.claude/`
- `~/.codex/`
- `~/.klaude/`
- `~/.agents/`

Example: `~/.claude/CLAUDE.md` applies to all projects.

### Project-level (per repo)

These directories are checked, relative to both the resolved working directory and nearest Git root (if present; resolved duplicates are removed):
- `<dir>/`
- `<dir>/.claude/`
- `<dir>/.agents/`

Example: `<project>/.claude/AGENTS.md` applies only when working in that project.

### Auto memory (agent-managed)

Both paths are checked in this order, subject to deduplication and the session budget:

- klaude: `~/.klaude/projects/<project_key>/memory/MEMORY.md`
- Claude Code: `~/.claude/projects/<claude_key>/memory/MEMORY.md`

Both keys use the resolved absolute working directory, not the Git root. For `project_key`, strip leading and trailing `/`, then replace remaining `/` with `-`. For `claude_key`, replace every `/` with `-`, including the leading `/`.

Example: `/Users/alice/code/my-project` becomes `Users-alice-code-my-project` for klaude and `-Users-alice-code-my-project` for Claude Code.

If neither file exists, the agent is prompted to create the klaude path when needed. Additional memory files can be read on demand.

## Path Discovery (dynamic)

For tracked accessed paths resolved inside the working directory, discovery checks each directory below the working directory through the file's parent (or the path itself if it is a directory). It checks only the three file names in each directory, not `.claude/` or `.agents/` there. Paths resolving outside the working directory are skipped.

Example: reading `src/foo/bar.py` checks `src/AGENTS.md`, `src/foo/AGENTS.md`, etc.

This enables per-module instructions:

```
my-project/
  AGENTS.md                    # project-wide instructions
  src/
    AGENTS.md                  # src-specific instructions
    klaude_code/
      auth/
        AGENTS.md              # auth-module-specific instructions
```

## Limits

| Limit | Value |
|-------|-------|
| Lines per memory file | First 200 lines |
| Bytes per memory file | 32 KiB after line truncation |
| Initial memory attachment session budget | 60 KiB |

Line and byte truncation include a note pointing to the full file; auto memory over 200 lines instead notes the original line count in its label. The session budget applies to global, project, and auto memory attachments: ordinary files may be truncated or skipped, while auto memory files that do not fit are skipped. Dynamically discovered path memories use the per-file limits but do not check this budget.

## Memory File Categories in System Prompt

| Source | Label |
|--------|-------|
| User-level (`~/.claude/`, etc.) | "user's private global instructions for all projects" |
| Project-level (work_dir, git root) | "project instructions, checked into the codebase" |
| Discovered near accessed path | "project instructions, discovered near last accessed path" |
| Auto memory (`MEMORY.md`) | "auto memory, persisted across sessions" |

## Best Practices

- Use `AGENTS.md` for project/module instructions that should be version-controlled.
- Use `~/.claude/CLAUDE.md` for personal preferences across all projects.
- Keep memory files concise -- they consume context window on every conversation.
- Use per-directory `AGENTS.md` for module-specific guidance (e.g., auth patterns, test conventions).
