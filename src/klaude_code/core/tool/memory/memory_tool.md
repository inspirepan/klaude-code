Stores and retrieves information across conversations through a memory file directory. Use this tool to persist knowledge, progress, and context that should survive between sessions.

The memory directory is located at `.claude/memories/` in the current project root (git repository root if present, otherwise the current working directory). Memories are scoped to the current project/directory and are not shared globally. All paths must start with `/memories` (e.g., `/memories/notes.txt`).

Commands:
- `view`: Show directory contents or file contents with optional line range
- `create`: Create or overwrite a file
- `str_replace`: Replace text in a file
- `insert`: Insert text at a specific line
- `delete`: Delete a file or directory
- `rename`: Rename or move a file/directory

Usage tips:
- Check your memory directory before starting tasks to recall previous context
- Record important decisions, progress, and learnings as you work
- Keep memory files organized and up-to-date; delete obsolete files

Note: when editing your memory folder, always try to keep its content up-to-date, coherent and organized. You can rename or delete files that are no longer relevant. Do not create new files unless necessary.

Only write down information relevant to current project in your memory system.