Writes a file to the local filesystem.

Usage:
This tool will overwrite the existing file if there is one at the provided path.
If this is an existing file, you MUST use the Read tool first to read the file's contents. This tool will fail if you did not read the file first.
Prefer `Edit` for existing files. Use `Write` only for a new file, or after reading an existing file and deciding to replace it end-to-end because most of it is changing. Do not create a file unless the task needs it, and do not proactively create documentation or README files.
Avoid writing an entire large file in one `Write` call. When creating a new large file, split the work into an initial `Write` of the skeleton followed by `Edit` calls to fill in sections.
