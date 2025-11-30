---
description: Create a comprehensive strategic plan with structured task breakdown
from: https://github.com/diet103/claude-code-infrastructure-showcase/blob/main/.claude/commands/dev-docs.md
---

Create a comprehensive, actionable plan for: 
$ARGUMENTS

## Instructions

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
   - Timeline Estimates

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

## Quality Standards
- Plans must be self-contained with all necessary context
- Use clear, actionable language
- Include specific technical details where relevant
- Consider both technical and business perspectives
- Account for potential risks and edge cases
