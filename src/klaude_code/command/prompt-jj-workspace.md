---
description: Create a jj workspace before starting work to enable parallel Clauding
---
<task>
$ARGUMENTS
</task>
<system>
You are now in jj-workspace mode. Before working on any task, you MUST first create a dedicated jj workspace. This allows multiple Claude sessions to work in parallel without conflicts.

If the <task> above is empty, inform the user that you are ready to work in jj-workspace mode and waiting for a task description. Once provided, follow the steps below.

When a task is provided, follow these steps:
1. Generate a short, descriptive workspace name based on the task (e.g., `workspace-add-login` or `workspace-fix-typo`)
2. Run `jj workspace add <workspace-name>` to create the workspace
3. Change into the workspace directory: `cd <workspace-name>`
4. Describe the change: `jj describe -m '<brief task description>'`
5. Continue all subsequent work within this workspace directory
</system>