---
name: skill-creator
description: Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.
metadata:
  short-description: Create or update a skill
---

# Skill Creator

This skill provides guidance for creating effective skills.

## About Skills

Skills are modular, self-contained packages that extend the agent's capabilities by providing
specialized knowledge, workflows, and tools. Think of them as "onboarding guides" for specific
domains or tasks - they transform the agent from a general-purpose assistant into a specialized
agent equipped with procedural knowledge.

### What Skills Provide

1. Specialized workflows - Multi-step procedures for specific domains
2. Tool integrations - Instructions for working with specific file formats or APIs
3. Domain expertise - Company-specific knowledge, schemas, business logic
4. Bundled resources - Scripts, references, and assets for complex and repetitive tasks

## Core Principles

### Concise is Key

The context window is a public good. Skills share the context window with everything else:
system prompt, conversation history, other Skills' metadata, and the actual user request.

**Default assumption: The agent is already very smart.** Only add context the agent doesn't
already have. Challenge each piece of information: "Does the agent really need this explanation?"
and "Does this paragraph justify its token cost?"

Prefer concise examples over verbose explanations.

### Anatomy of a Skill

Every skill consists of a required SKILL.md file and optional bundled resources:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/          - Executable code (Python/Bash/etc.)
    ├── references/       - Documentation intended to be loaded into context as needed
    └── assets/           - Files used in output (templates, icons, fonts, etc.)
```

#### SKILL.md (required)

Every SKILL.md consists of:

- **Frontmatter** (YAML): Contains `name` and `description` fields. These are the only fields
  that determine when the skill gets used, thus it is very important to be clear and comprehensive
  in describing what the skill is, and when it should be used.
- **Body** (Markdown): Instructions and guidance for using the skill. Only loaded AFTER the
  skill triggers (if at all).

#### Bundled Resources (optional)

Use bundled resources to keep SKILL.md lean via **progressive disclosure**: load information
only when the agent needs it.

Key rules for all bundled resources:
- Keep files **one level deep** only (e.g., `references/schema.md`, not
  `references/db/v1/schema.md`).
- Always use **relative paths** with forward slashes (`/`), regardless of OS.
- Use **Just-in-Time loading** -- explicitly instruct the agent in SKILL.md when to read a
  file. The agent will not see these resources unless directed to. Example: *"Read
  `references/auth-flow.md` for the complete error code table."*

##### Scripts (`scripts/`)

Executable code (Python/Bash/etc.) for tasks that require deterministic reliability or are
repeatedly rewritten.

- **When to include**: When the same code is being rewritten repeatedly or deterministic
  reliability is needed
- **Example**: `scripts/rotate_pdf.py` for PDF rotation tasks
- **Error messages matter**: The agent relies on stdout/stderr to determine success or
  failure. Write scripts that return descriptive, human-readable error messages so the agent
  can self-correct without user intervention.
- Do not bundle long-lived library code here; skills should contain tiny, single-purpose
  scripts only.

##### References (`references/`)

Documentation and reference material intended to be loaded as needed into context.

- **When to include**: For documentation that the agent should reference while working
- **Examples**: `references/schema.md` for database schemas, `references/api_docs.md` for
  API specifications

##### Assets (`assets/`)

Files not intended to be loaded into context, but rather used within the output. Agents
pattern-match exceptionally well -- prefer placing a concrete template in `assets/` over
writing paragraphs that describe the desired output format.

- **When to include**: When the skill needs files that will be used in the final output, or
  concrete templates the agent should copy the structure of
- **Examples**: `assets/logo.png` for brand assets, `assets/template.html` for HTML templates

## Skill Creation Process

Skill creation involves these steps:

1. Understand the skill with concrete examples
2. Plan reusable skill contents (scripts, references, assets)
3. Create the skill directory structure
4. Write SKILL.md with proper frontmatter
5. Add bundled resources as needed
6. Present verification suggestions to the user (see below)

### Post-Creation Verification Suggestions

After creating or updating a skill, generate a short list of **concrete, actionable
verification suggestions** tailored to the specific skill, so the user can test it themselves.
Cover three angles:

1. **Discovery** -- suggest 2-3 example prompts the user can try to confirm the skill
   triggers correctly, and 1-2 similar-but-different prompts that should NOT trigger it.
2. **Logic** -- suggest a realistic end-to-end task the user can run to check whether the
   agent follows each step without getting stuck or hallucinating missing information.
3. **Edge cases** -- name 1-2 tricky scenarios specific to this skill's domain that the user
   should try to make sure the skill handles them (or fails gracefully).

Present these as a checklist the user can walk through. Keep it brief and specific to the
skill just created -- not generic advice.

### Skill Naming

- Use lowercase letters, digits, and hyphens only
- Prefer short, verb-led phrases that describe the action
- Name the skill folder exactly after the skill name

### Writing Guidelines

Always use imperative/infinitive form.

#### Frontmatter

Write the YAML frontmatter with `name` and `description`:

- `name`: The skill name (required)
- `description`: This is the primary triggering mechanism for your skill. The agent sees
  **only** this field when deciding whether to load the skill. Include both what the skill
  does and specific triggers for when to use it. Include "negative triggers" to prevent
  false matches on similar-sounding requests.
  - **Bad:** `"React skills."` -- too vague, triggers on everything React-adjacent.
  - **Good:** `"Creates and builds React components using Tailwind CSS. Use when the user
    wants to update component styles or UI logic. Do not use for Vue, Svelte, or vanilla
    CSS projects."` -- states capability, trigger context, and exclusions.

#### Body

Write instructions for using the skill and its bundled resources. Keep SKILL.md body to the
essentials and under 500 lines to minimize context bloat.

Skills are instructions for agents, not documentation for humans. Follow these writing rules:

- **Use numbered steps, not prose.** Define workflows as strict chronological sequences. For
  decision trees, map branches explicitly (e.g., *"Step 2: If source maps are needed, run
  `ng build --source-map`. Otherwise, skip to Step 3."*).
- **Write in third-person imperative.** Frame instructions as direct commands: *"Extract the
  text..."* rather than *"I will extract..."* or *"You should extract..."*.
- **Prefer templates over descriptions.** Place concrete output templates in `assets/` and
  instruct the agent to copy the structure, instead of describing the format in paragraphs.
- **Use consistent terminology.** Pick one term per concept and use it everywhere. Prefer
  domain-native terms (e.g., Angular "template" instead of "html" or "markup").

### What NOT to Create

Do not create files that waste tokens or duplicate what the agent already knows:

- **Documentation files** (`README.md`, `CHANGELOG.md`) -- skills are not human-facing docs.
- **Redundant instructions** -- if the agent handles a task reliably without guidance, omit it.
- **Library code** -- long-lived library code belongs in standard repo directories, not in
  `scripts/`.

## Skill Storage Locations

Skills can be stored in multiple locations with the following priority (higher priority overrides lower):

| Priority | Scope   | Path                | Description          |
|----------|---------|---------------------|----------------------|
| 1        | Project | `.agents/skills/`   | Current project only |
| 2        | Project | `.claude/skills/`   | Current project only |
| 3        | User    | `~/.agents/skills/` | User-level           |
| 4        | User    | `~/.claude/skills/` | User-level (Claude)  |

If the user does not explicitly specify project-level vs user-level, ask a clarification question before creating or updating the skill.
