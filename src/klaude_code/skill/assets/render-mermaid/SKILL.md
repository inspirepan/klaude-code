---
name: "render-mermaid"
description: "Use when the user asks you to analyze a repository, draw an architecture diagram, analyze a workflow/process, or explain something through a visual diagram. Prefer this skill whenever structured relationships, flows, states, sequences, or decision paths need to be communicated clearly. Do not use for general image generation or non-Mermaid charting tools."
---

# Render Mermaid Skill

## Workflow
1. Identify whether visualization is needed: if the user is discussing architecture, dependencies, processes, states, sequences, entity relationships, or branching decisions, prioritize providing Mermaid diagrams.
2. Generate Mermaid source code (`graph` / `flowchart` / `sequenceDiagram` / `classDiagram` / `erDiagram` / `stateDiagram-v2`, etc.).
3. Choose an output path with `.svg` suffix.
4. Run the command to render:

```bash
bun scripts/render_mermaid.js \
  --output "<OUTPUT_PATH>.svg" <<'MERMAID'
<MERMAID_TEXT>
MERMAID
```

Use this stdin heredoc form only in this skill to avoid command-style confusion.

5. On success, read the image path from the script output and return it to the user using markdown image syntax (e.g., `![Mermaid Architecture Diagram](/tmp/render-mermaid-arch.svg)`) so the system can render the image for the user; on failure, relay the error message as-is, correct the Mermaid diagram, and retry.

## Notes
- The script renders using the npm package `beautiful-mermaid` (loaded via the Bun runtime).
- The script outputs SVG images only.
