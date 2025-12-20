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

##### Scripts (`scripts/`)

Executable code (Python/Bash/etc.) for tasks that require deterministic reliability or are
repeatedly rewritten.

- **When to include**: When the same code is being rewritten repeatedly or deterministic
  reliability is needed
- **Example**: `scripts/rotate_pdf.py` for PDF rotation tasks
- **Benefits**: Token efficient, deterministic, may be executed without loading into context

##### References (`references/`)

Documentation and reference material intended to be loaded as needed into context.

- **When to include**: For documentation that the agent should reference while working
- **Examples**: `references/schema.md` for database schemas, `references/api_docs.md` for
  API specifications
- **Benefits**: Keeps SKILL.md lean, loaded only when needed

##### Assets (`assets/`)

Files not intended to be loaded into context, but rather used within the output.

- **When to include**: When the skill needs files that will be used in the final output
- **Examples**: `assets/logo.png` for brand assets, `assets/template.html` for HTML templates
- **Benefits**: Separates output resources from documentation

## Skill Creation Process

Skill creation involves these steps:

1. Understand the skill with concrete examples
2. Plan reusable skill contents (scripts, references, assets)
3. Create the skill directory structure
4. Write SKILL.md with proper frontmatter
5. Add bundled resources as needed
6. Test and iterate based on real usage

### Skill Naming

- Use lowercase letters, digits, and hyphens only
- Prefer short, verb-led phrases that describe the action
- Name the skill folder exactly after the skill name

### Writing Guidelines

Always use imperative/infinitive form.

#### Frontmatter

Write the YAML frontmatter with `name` and `description`:

- `name`: The skill name (required)
- `description`: This is the primary triggering mechanism for your skill. Include both what
  the Skill does and specific triggers/contexts for when to use it. Include all "when to use"
  information here - Not in the body.

#### Body

Write instructions for using the skill and its bundled resources. Keep SKILL.md body to the
essentials and under 500 lines to minimize context bloat.

## Skill Storage Locations

Skills can be stored in multiple locations with the following priority (higher priority overrides lower):

| Priority | Scope   | Path                        | Description           |
|----------|---------|-----------------------------|-----------------------|
| 1        | Project | `.claude/skills/`           | Current project only  |
| 2        | User    | `~/.klaude/skills/`         | User-level            |
| 3        | User    | `~/.claude/skills/`         | User-level (Claude)   |
| 4        | System  | `~/.klaude/skills/.system/` | Built-in system skills|
