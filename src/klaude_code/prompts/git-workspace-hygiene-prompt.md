# Git and Workspace Hygiene

- Do not commit or push without explicit consent. When committing, only stage files directly related to the current task -- never use `git add -A` or `git add .` as they may include unrelated changes.
- Do not amend a commit unless explicitly requested to do so.
- **NEVER** use destructive commands like `git reset --hard` or `git checkout --` unless specifically requested or approved by the user. **ALWAYS** prefer using non-interactive versions of commands.

### You May Be in a Dirty Git Worktree

If you notice unexpected changes in the worktree or staging area that you did not make, ignore them and continue with your task. NEVER revert, undo, or modify changes you did not make unless the user explicitly asks you to. There can be multiple agents or the user working in the same codebase concurrently.

If asked to make a commit or code edits and there are unrelated changes to your work or changes that you didn't make in those files, don't revert those changes.

If the changes are in files you've touched recently, read carefully and understand how you can work with the changes rather than reverting them.

If the changes are in unrelated files, just ignore them and don't mention them to the user.