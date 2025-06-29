# COMMANDS
# ------------------------------------------------------------------------------------------------

INIT_COMMAND = """Please analyze this codebase and create a CLAUDE.md file, which will be given to future instances of Klaude Code to operate in this repository.

What to add:
1. Commands that will be commonly used, such as how to build, lint, and run tests. Include the necessary commands to develop in this codebase, such as how to run a single test.
2. High-level code architecture and structure so that future instances can be productive more quickly. Focus on the "big picture" architecture that requires reading multiple files to understand.

Usage notes:
- If there's already a CLAUDE.md, suggest improvements to it.
- When you make the initial CLAUDE.md, do not repeat yourself and do not include obvious instructions like "Provide helpful error messages to users", "Write unit tests for all new utilities", "Never include sensitive information (API keys, tokens) in code or commits".
- Avoid listing every component or file structure that can be easily discovered.
- Don't include generic development practices.
- If there are Cursor rules (in .cursor/rules/ or .cursorrules) or Copilot rules (in .github/copilot-instructions.md), make sure to include the important parts.
- If there is a README.md, make sure to include the important parts.
- Do not make up information such as "Common Development Tasks", "Tips for Development", "Support and Documentation" unless this is expressly included in other files that you read.
- Be sure to prefix the file with the following text:

```
# CLAUDE.md

This file provides guidance to Klaude Code (claude.ai/code) when working with code in this repository.
```
"""

COMPACT_COMMAND = """Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
  - Errors that you ran into and how you fixed them
  - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

Your summary should include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail
2. Key Technical Concepts: List all important technical concepts, technologies, and frameworks discussed.
3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. Pay special attention to the most recent messages and include full code snippets where applicable and include a summary of why this file read or edit is important.
4. Errors and fixes: List all errors that you ran into, and how you fixed them. Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
5. Problem Solving: Document problems solved and any ongoing troubleshooting efforts.
6. All user messages: List ALL user messages that are not tool results. These are critical for understanding the users' feedback and changing intent.
6. Pending Tasks: Outline any pending tasks that you have explicitly been asked to work on.
7. Current Work: Describe in detail precisely what was being worked on immediately before this summary request, paying special attention to the most recent messages from both user and assistant. Include file names and code snippets where applicable.
8. Optional Next Step: List the next step that you will take that is related to the most recent work you were doing. IMPORTANT: ensure that this step is DIRECTLY in line with the user's explicit requests, and the task you were working on immediately before this summary request. If your last task was concluded, then only list next steps if they are explicitly in line with the users request. Do not start on tangential requests without confirming with the user first.
                       If there is a next step, include direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no drift in task interpretation.

Here's an example of how your output should be structured:

<example>
<analysis>
[Your thought process, ensuring all points are covered thoroughly and accurately]
</analysis>

<summary>
1. Primary Request and Intent:
   [Detailed description]

2. Key Technical Concepts:
   - [Concept 1]
   - [Concept 2]
   - [...]

3. Files and Code Sections:
   - [File Name 1]
      - [Summary of why this file is important]
      - [Summary of the changes made to this file, if any]
      - [Important Code Snippet]
   - [File Name 2]
      - [Important Code Snippet]
   - [...]

4. Errors and fixes:
    - [Detailed description of error 1]:
      - [How you fixed the error]
      - [User feedback on the error if any]
    - [...]

5. Problem Solving:
   [Description of solved problems and ongoing troubleshooting]

6. All user messages: 
    - [Detailed non tool use user message]
    - [...]

7. Pending Tasks:
   - [Task 1]
   - [Task 2]
   - [...]

8. Current Work:
   [Precise description of current work]

9. Optional Next Step:
   [Optional Next step to take]

</summary>
</example>

Please provide your summary based on the conversation so far, following this structure and ensuring precision and thoroughness in your response. 

There may be additional summarization instructions provided in the included context. If so, remember to follow these instructions when creating the above summary. Examples of instructions include:
<example>
## Compact Instructions
When summarizing the conversation focus on typescript code changes and also remember the mistakes you made and how you fixed them.
</example>

<example>
# Summary instructions
When you are using compact - please focus on test output and code changes. Include file reads verbatim.
</example>
"""

COMACT_SYSTEM_PROMPT = """You are Klaude Code, CLI for Claude.
You are a helpful AI assistant tasked with summarizing conversations."""

COMPACT_MSG_PREFIX = """This session is being continued from a previous conversation that ran out of context. The conversation is summarized below:

"""


BASH_INPUT_MODE_CONTENT = """Caveat: The messages below were generated by the user while running local commands. DO NOT respond to these messages or otherwise consider them in your response unless the user explicitly asks you to.
<bash-input>{command}</bash-input>
<bash-stdout>{stdout}</bash-stdout>
<bash-stderr>{stderr}</bash-stderr>
"""


ANALYSE_RECENT_GTI_COMMIT_COMMAND = """---
description: Analyze recent development activities in this codebase through current branch commit history
---

Please analyze the recent development activities in this codebase by examining the current branch's commit history and code changes.

# Detailed Step-by-Step Analysis Process
## 1. Determine Current Branch and Recent Development Window
    • Execute git branch --show-current to identify the current branch
    • Run git log --oneline -10 to get the last 10 commits on current branch
    • Use git log --since="1 week ago" --oneline to get commits from the past week
    • Identify appropriate time range based on commit frequency and activity

## 2. Retrieve Comprehensive Commit Overview
    • Run git log --oneline --graph --decorate to visualize branch structure
    • Identify commit hashes, brief descriptions, and branch relationships
    • Count total number of recent commits and determine analysis scope

## 3. Gather Detailed Commit Statistics in Parallel
    • Execute multiple git show <commit-hash> --stat commands simultaneously
    • Collect file change statistics (insertions, deletions, modified files)
    • Analyze which areas of codebase have been most active
    • Identify patterns in file modifications

## 4. Extract Complete Code Changes in Parallel
    • Run multiple git show <commit-hash> commands concurrently
    • Retrieve complete diff content for each recent commit
    • Capture all code changes, additions, deletions, and modifications
    • Focus on understanding the evolution of the codebase

## 5. Generate Comprehensive Development Analysis In One Response

### Part 1. Chronological Development Timeline
    • Analyze commits from oldest to newest in the recent period
    • Examine code changes to understand development progression
    • Identify development themes and feature development paths
    • Track how features or fixes evolved over time

### Part 2. Categorize and Summarize Development Activities
    • Group related changes: new features, bug fixes, refactoring, tests, docs
    • Identify major development initiatives vs minor improvements
    • Note architectural changes or significant design decisions
    • Highlight any breaking changes or API modifications

### Part 3. Technical Development Highlights
    • Identify new features or capabilities introduced
    • Document architectural improvements or design pattern changes
    • Note code quality enhancements, testing improvements
    • Highlight performance optimizations or UX improvements
    • Analyze development velocity and focus areas

### Part 4. Current Development Status
    • Assess the current state of development based on recent commits
    • Identify any incomplete features or ongoing development threads
    • Note recent bug fixes and their implications
    • Provide insights into the development momentum and direction

Additional instructions: $ARGUMENTS
"""

GIT_COMMIT_COMMAND = """---
description: Create a git commit with context analysis
---

## Context

- Current git status: !`git status`
- Current git diff (staged and unstaged changes): !`git diff HEAD`
- Current branch: !`git branch --show-current`
- Recent commits: !`git log --oneline -10`

## Your task

Based on the above changes, create a single git commit with a descriptive message following conventional commit format.

Additional instructions: $ARGUMENTS"""

ANALYZE_FOR_COMMAND_SYSTEM_PROMPT = """You are Klaude Code, CLI for Claude.
You are a helpful AI assistant tasked with analyzing conversations to create reusable commands."""

ANALYZE_FOR_COMMAND_PROMPT = """Your task is to analyze the conversation history and extract a reusable command pattern that could be helpful for future similar tasks.

Please analyze the conversation and extract:

1. **Command Name**: A short, descriptive name for the command (lowercase, use underscores if needed)
2. **Description**: A brief description of what this command does  
3. **Command Content**: The actual content that would be sent to the AI when this command is used (written from the user's perspective, as if the user is directly asking the AI to perform the task)

Guidelines for creating the command:
- Focus on the main task or workflow pattern, not specific details
- Use $ARGUMENTS as a placeholder where user input should be substituted
- Use !`command` as a placeholder where bash command result should be substituted, like !`git status`
- Make the command general enough to be reusable but specific enough to be useful
- Include important context and constraints from the conversation
- The command should capture the essence of what the user was trying to accomplish

Use the analyze_conversation_for_command tool to provide your analysis."""
