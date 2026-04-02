Runs a non-interactive shell command and returns stdout/stderr.

For long-running scripts, print progress regularly so users can see activity:
- Prefer line-by-line progress logs (`print(...)`, `echo ...`) during loops/batches.
- For Python scripts, make progress output unbuffered (`print(..., flush=True)` or `python -u ...`) to avoid delayed logs.