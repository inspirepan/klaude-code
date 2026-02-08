---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code
---

# Writing Plans

## Overview

Write clear implementation plans that describe **intent, not code**. Document which files to touch, what each task should achieve, and how to verify it. The executing engineer is a skilled AI developer who can write the code themselves -- they need to understand *what* to build and *why*, not be given copy-paste snippets. DRY. YAGNI. TDD. Frequent commits.

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

**Save plans to:** `docs/plans/YYYY-MM-DD-<feature-name>.md`

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" - step
- "Run it to make sure it fails" - step
- "Implement the minimal code to make the test pass" - step
- "Run the tests and make sure they pass" - step
- "Commit" - step

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For Claude:** Use the executing-plans skill to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

## Task Structure

```markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py`
- Test: `tests/exact/path/to/test.py`

**Intent:** What this task achieves and why.

**Steps:**
1. Write a failing test that verifies [specific behavior]
2. Implement [component/function] to make the test pass
3. Verify: `pytest tests/path/test.py -v`
4. Commit: `feat: add specific feature`

**Acceptance criteria:**
- [Concrete, verifiable outcome 1]
- [Concrete, verifiable outcome 2]

**Notes:** Any gotchas, edge cases, or references to existing patterns in the codebase.
```

## Remember
- Exact file paths always
- Describe intent and acceptance criteria, not full code
- Only include code snippets for non-obvious APIs, data structures, or tricky interfaces
- Exact verification commands
- DRY, YAGNI, TDD, frequent commits

## Execution Handoff

After saving the plan:

**"Plan complete and saved to `docs/plans/<filename>.md`. Ready to execute using the executing-plans skill, or would you prefer to review the plan first?"**
