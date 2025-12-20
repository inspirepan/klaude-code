---
name: dev-docs
description: Manage development documentation for complex tasks. Use this skill when users want to create a strategic plan with structured task breakdown, or update development documentation before context compaction/reset. Triggers include "create a plan", "dev docs", "update docs before context reset", "context limit approaching".
metadata:
  short-description: Create and update development documentation
---

# Dev Docs

Manage development documentation for complex, multi-phase tasks. This skill supports two workflows:
1. **Create**: Generate a comprehensive strategic plan with structured task breakdown
2. **Update**: Update documentation before context compaction or reset

## Create Development Plan

When creating a new plan:

1. **Analyze the request** and determine the scope of planning needed
2. **Examine relevant files** in the codebase to understand current state
3. **Create a structured plan** with:
   - Executive Summary
   - Current State Analysis
   - Proposed Future State
   - Implementation Phases (broken into sections)
   - Detailed Tasks (actionable items with clear acceptance criteria)
   - Risk Assessment and Mitigation Strategies
   - Success Metrics
   - Required Resources and Dependencies

4. **Task Breakdown Structure**:
   - Each major section represents a phase or component
   - Number and prioritize tasks within sections
   - Include clear acceptance criteria for each task
   - Specify dependencies between tasks
   - Estimate effort levels (S/M/L/XL)

5. **Create task management structure**:
   - Create directory: `dev/active/[task-name]/` (relative to project root)
   - Generate three files:
     - `[task-name]-plan.md` - The comprehensive plan
     - `[task-name]-context.md` - Key files, decisions, dependencies
     - `[task-name]-tasks.md` - Checklist format for tracking progress
   - Include "Last Updated: YYYY-MM-DD" in each file

6. **Stop and Consult**: Pause and negotiate the plan with the user.

### Quality Standards

- Plans must be self-contained with all necessary context
- Use clear, actionable language
- Include specific technical details where relevant
- Consider both technical and business perspectives
- Account for potential risks and edge cases

## Update Development Documentation

When approaching context limits or before context reset:

### 1. Update Active Task Documentation

For each task in `/dev/active/`:

Update `[task-name]-context.md` with:
- Current implementation state
- Key decisions made this session
- Files modified and why
- Any blockers or issues discovered
- Next immediate steps
- Last Updated timestamp

Update `[task-name]-tasks.md` with:
- Mark completed tasks with checkmark
- Add any new tasks discovered
- Update in-progress tasks with current status
- Reorder priorities if needed

### 2. Capture Session Context

Include any relevant information about:
- Complex problems solved
- Architectural decisions made
- Tricky bugs found and fixed
- Integration points discovered
- Testing approaches used
- Performance optimizations made

### 3. Update Memory (if applicable)

- Store any new patterns or solutions in project memory/documentation
- Update entity relationships discovered
- Add observations about system behavior

### 4. Document Unfinished Work

- What was being worked on when context limit approached
- Exact state of any partially completed features
- Commands that need to be run on restart
- Any temporary workarounds that need permanent fixes

### 5. Create Handoff Notes

If switching to a new conversation:
- Exact file and line being edited
- The goal of current changes
- Any uncommitted changes that need attention
- Test commands to verify work

**Priority**: Focus on capturing information that would be hard to rediscover or reconstruct from code alone.
