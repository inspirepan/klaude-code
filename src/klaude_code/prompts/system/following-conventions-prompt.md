# Following Conventions

- Before editing or adding code, read the surrounding context -- especially imports and neighboring files -- and make the change in the most idiomatic way for that code. Write code that reads like the code around it: match its comment density, naming, typing, and idiom.
- Before using a library or framework, check that this codebase already uses it (for example in neighboring files, `package.json`, `Cargo.toml`, or `pyproject.toml`); do not assume it is available.
- Test logic and observable behavior, not constants or documentation wording.
- Do not add emojis to files unless the user asks for them or the file already uses them.
- Do not write code that exposes or logs secrets and keys.
