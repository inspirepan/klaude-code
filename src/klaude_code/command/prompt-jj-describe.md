---
description: Add description for current jj change
---

Run `jj status` and `jj diff --git` to see the current changes and add a description for the it.

In order to ensure good formatting, ALWAYS pass the commit message via a HEREDOC, a la this example:<example>
jj describe -m "$(cat <<'EOF'
   Commit message here.
   EOF
   )"
</example>

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:
```
<type>(<scope>): <description>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring (no feature or fix)
- `test`: Adding or updating tests
- `chore`: Build process, dependencies, or tooling changes

Examples:
- `feat(cli): add --verbose flag for debug output`
- `fix(llm): handle API timeout errors gracefully`
- `docs(readme): update installation instructions`
- `refactor(core): simplify session state management`