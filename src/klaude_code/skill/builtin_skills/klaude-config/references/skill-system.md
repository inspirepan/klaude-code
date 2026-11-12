---
name: skill-system
description: Skill directories, priority, installation, SKILL.md format, and dynamic discovery
---

# Skill System Reference

Skills are `SKILL.md` files with YAML frontmatter. The available-skills reminder contains metadata, not the full instructions. The agent reads a relevant file on demand; `/skill:name` or `//skill:name` explicitly activates and inlines it in a developer-message reminder (up to 500 lines, with a pointer to the rest).

## Skill Directories

Listed from lowest to highest priority. Higher priority overrides lower when names collide.

### User skills
Checked in order (later directories override earlier ones with same skill name):
1. `~/.claude/skills/`
2. `~/.klaude/skills/`
3. `~/.agents/skills/`
4. `~/.config/agents/skills/`

### Project skills (highest priority)
At every ancestor from filesystem root to the working directory; nearest directory wins:
1. `./.claude/skills/`
2. `./.agents/skills/`

## Installing a Skill

Install shared skills with `npx skills add inspirepan/agent-skills --global --agent codex claude-code --skill klaude-config`. klaude reads `~/.agents/skills/` directly. Discovery recursively scans skill directories, skips hidden child directories, and follows directory symlinks.

Alternatively, place a directory containing `SKILL.md` into any user or project skill directory:

```
~/.agents/skills/my-skill/SKILL.md        # user-level
./.claude/skills/my-skill/SKILL.md        # project-level
```

The directory name should match the `name` field. A mismatch produces a warning but does not prevent loading.

## SKILL.md Format

```yaml
---
name: my-skill                    # should match directory name
description: >-                   # required; determines when agent loads the skill
  Use when the user asks to do X.
  Triggers: "keyword1", "keyword2".
license: MIT                      # optional
metadata:
  short-description: Brief label  # optional; shown in completions
allowed-tools:                    # optional metadata, parsed as a list
  - Bash
  - Read
---

# Skill Title

Instructions in Markdown. The agent reads this file when relevant.

## References

Link to files in references/ directory for detailed docs:
- [detailed-guide.md](references/detailed-guide.md)
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | no | Skill identifier. Empty or missing defaults to directory name; a mismatch warns. |
| `description` | **yes** | Determines relevance. Include trigger words/phrases. |
| `license` | no | License identifier. |
| `metadata` | no | Key-value pairs. `short-description` used for completions. |
| `allowed-tools` | no | Parsed as a list when present; the loader does not enforce tool restrictions. |

## Dynamic Discovery

When the agent accesses a path, discovery checks `.claude/skills/` and `.agents/skills/` from its directory upward:

- Inside the resolved working directory, stop before the working directory itself, which static discovery already covers.
- Outside it, include the nearest Git root as the boundary; without a Git root, check only the accessed path's directory.

Discovered skills are announced as metadata in a reminder; the agent reads relevant instructions as needed. Symlink-resolved paths determine the boundary.

This means project subdirectories can define their own skills:

```
my-project/
  .claude/skills/top-skill/SKILL.md      # discovered at startup
  packages/api/
    .claude/skills/api-skill/SKILL.md    # discovered when agent reads files under packages/api/
```

When multiple nested directories define the same skill name, the deeper definition wins.

## Override Behavior

If two skills share the same `name`, the higher-priority level wins:
- Project skills override user skills
- Within the same level, later directories override earlier ones

Static discovery records warnings for duplicate names at different resolved paths; identical resolved paths are silently deduplicated. For explicit activation, an exact dynamic match takes precedence over a static match.

## References Directory Convention

Use a `references/` subdirectory for detailed documentation that the SKILL.md links to:

```
my-skill/
  SKILL.md              # concise entry point
  references/
    detailed-guide.md   # loaded on demand via Read tool
    api-reference.md
  scripts/
    helper.py           # bundled scripts
```

The agent reads reference files on demand -- they are not loaded into the system prompt automatically.
