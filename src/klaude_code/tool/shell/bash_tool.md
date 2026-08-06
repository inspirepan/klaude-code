Runs a non-interactive shell command and returns stdout/stderr.

Usage:
- Every call starts a fresh shell in the session working directory; `cd` never carries over between calls. To run somewhere else, chain it in the same command: `cd worker && pnpm test`.
- Prefer `rg` and `rg --files` for text and file search. Use `git log` and `git blame` to search codebase history.
- Do not use Python for simple file reads/writes.
- Do not chain unrelated commands with separator prints like `echo "===";` -- the merged output renders poorly. Run them as separate calls, in parallel when independent.
- For long-running scripts, print line-by-line progress during loops/batches so the user can see activity. Make Python output unbuffered (`print(..., flush=True)` or `python -u ...`) to avoid delayed logs.

`rm` and `trash` operands are restricted to relative paths that resolve inside the workspace: absolute paths, `~`, wildcards, and trailing slashes are rejected, and `rm -r` additionally requires an existing non-symlink target. Other commands are unrestricted.
