---
name: deslop
description: Remove AI-generated code slop from files or diffs. Use this skill when reviewing AI-generated code to clean up unnecessary comments, defensive code, type hacks, and style inconsistencies. Triggers include "deslop", "remove slop", "clean up AI code", "review for slop".
metadata:
  short-description: Remove AI code slop
---

# Deslop

Remove AI-generated slop from code. Check the specified files or diff and remove:

- Extra comments that a human wouldn't add or are inconsistent with the rest of the file
- Extra defensive checks or try/catch blocks that are abnormal for that area of the codebase (especially if called by trusted/validated codepaths)
- Casts to `any` or `# type: ignore` to get around type issues
- Any other style that is inconsistent with the file

Report at the end with only a 1-3 sentence summary of what you changed.
