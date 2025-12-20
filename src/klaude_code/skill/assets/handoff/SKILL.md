---
name: handoff
description: Write a HANDOFF.md file for another agent to continue the conversation. Use this skill when switching to a new conversation/session and need to pass context to the next agent. Triggers include "handoff", "write handoff", "create handoff", "pass to another agent".
metadata:
  short-description: Write handoff document for agent continuation
---

# Handoff

Write a HANDOFF.md file in the current working directory for another agent to continue this conversation.

Extract relevant context from the conversation to facilitate continuing this work. Write from the user's perspective (first person: "I did...", "I told you...").

## Consider What Would Be Useful

- What did the user just do or implement?
- What instructions did the user give that are still relevant (e.g., follow patterns in the codebase)?
- Did the user provide a plan or spec that should be included?
- What important information did the user share (certain libraries, patterns, constraints, preferences)?
- What key technical details were discovered (APIs, methods, patterns)?
- What caveats, limitations, or open questions remain?

Extract only what matters for the specific goal. Skip irrelevant questions. Choose an appropriate length based on the complexity.

Focus on capabilities and behavior, not file-by-file changes. Avoid excessive implementation details (variable names, storage keys, constants) unless critical.

## Format

- Plain text with bullets
- No markdown headers, no bold/italic, no code fences
- Use workspace-relative paths for files
- List relevant file or directory paths at the end:

```
@src/project/main.py
@src/project/llm/
```

If the user's goal is unclear, ask for clarification.
