Moves a range of lines from one file to another.

Usage:
- Cuts lines from `start_line` to `end_line` (inclusive, 1-indexed) from the source file
- Pastes them into the target file at `insert_line` (inserted before that line)
- Both files must have been read first using the Read tool
- To create a new target file, set `insert_line` to 1 and ensure target file does not exist
- For same-file moves, line numbers refer to the original file state before any changes
- Use this tool when refactoring code into separate modules to avoid passing large code blocks twice
- To move files or directories, use the Bash tool with `mv` command instead

Return format:
The tool returns context snippets showing the state after the operation:

1. Source file context (after cut): Shows 3 lines before and after the cut location
2. Target file context (after insert): Shows 3 lines before the inserted content, the inserted content itself, and 3 lines after

Example output:
```
Cut 8 lines from /path/source.py (lines 9-16) and pasted into /path/target.py (updated) at line 10.

Source file context (after cut):
     6	    return value
     7	
     8	
  -------- cut here --------
     9	class NextClass:
    10	    pass
    11	

Target file context (after insert):
     7	    return {}
     8	
     9	
  -------- inserted --------
    10	class MovedClass:
    ...
    17	        return result
  -------- end --------
    18	# Next section
```
