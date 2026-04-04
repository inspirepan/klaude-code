Apply a patch to files within the workspace. The patch must use the following format:

```
*** Begin Patch
*** Update File: path/to/file
 context line
-old line
+new line
@@ section header
 more context
*** Add File: path/to/new_file
+line 1
+line 2
*** Delete File: path/to/old_file
*** End Patch
```

Rules:
- Each file path may only appear ONCE in a patch. Do not combine Delete + Add for the same path; use Update instead.
- Update File: modify an existing file. Use context lines (no prefix), `-` for removals, `+` for additions, and `@@ line` to jump to a section.
- Add File: create a new file. Every content line must start with `+`.
- Delete File: remove an existing file entirely. No content lines.
- Update File supports `*** Move to: new/path` on the next line to rename/move a file.
