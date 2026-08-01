# Following Conventions

- Before editing or adding code, read the surrounding context -- especially imports and neighboring files -- and make the change in the most idiomatic way for that code. Write code that reads like the code around it: match its comment density, naming, typing, and idiom.
- NEVER assume a given library is available. Before using a library or framework, check that this codebase already uses it (e.g., check neighboring files, `package.json`, `cargo.toml`, `pyproject.toml`, etc.).
- Test logic and observable behavior, not constants or documentation wording.
- Do not add emojis to files unless the user asks for them or the file already uses them.
- Always follow security best practices. Never introduce code that exposes or logs secrets and keys.
