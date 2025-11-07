# 实现 Read, Edit 与 MultiEdit 工具 

位置： @src/codex_mini/core/tool/ 下
请你理解现有的工具实现 (bash_tool.py)，实现三个新的工具


## Schema
下面是 Read、Edit 和 MultiEdit 的描述和 Schema，请原封不动地设置为工具的描述和 Schema，不要修改

### Read
Desc:
```
Reads a file from the local filesystem. You can access any file directly by using this tool.
Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- This tool can only read files, not directories. To read a directory, use an ls command via the Bash tool.
- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful. 
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.
```

Params:
{
  "type": "object",
  "properties": {
    "file_path": {
      "type": "string",
      "description": "The absolute path to the file to read"
    },
    "offset": {
      "type": "number",
      "description": "The line number to start reading from. Only provide if the file is too large to read at once"
    },
    "limit": {
      "type": "number",
      "description": "The number of lines to read. Only provide if the file is too large to read at once."
    }
  },
  "required": [
    "file_path"
  ],
  "additionalProperties": false,
}


## Edit
Desc:
```
Performs exact string replacements in files.

Performs exact string replacements in files. 

Usage:
- You must use your `Read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file. 
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`. 
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.
- You can use this tool to create new files by providing an empty old_string.
```

Params:
{
  "type": "object",
  "properties": {
    "file_path": {
      "type": "string",
      "description": "The absolute path to the file to modify"
    },
    "old_string": {
      "type": "string",
      "description": "The text to replace"
    },
    "new_string": {
      "type": "string",
      "description": "The text to replace it with (must be different from old_string)"
    },
    "replace_all": {
      "type": "boolean",
      "default": false,
      "description": "Replace all occurences of old_string (default false)"
    }
  },
  "required": [
    "file_path",
    "old_string",
    "new_string"
  ],
  "additionalProperties": false,
}

## MultiEdit
Desc:
```
This is a tool for making multiple edits to a single file in one operation. It is built on top of the Edit tool and allows you to perform multiple find-and-replace operations efficiently. Prefer this tool over the Edit tool when you need to make multiple edits to the same file.

Before using this tool:

1. Use the Read tool to understand the file's contents and context
2. Verify the directory path is correct

To make multiple file edits, provide the following:
1. file_path: The absolute path to the file to modify (must be absolute, not relative)
2. edits: An array of edit operations to perform, where each edit contains:
   - old_string: The text to replace (must match the file contents exactly, including all whitespace and indentation)
   - new_string: The edited text to replace the old_string
   - replace_all: Replace all occurences of old_string. This parameter is optional and defaults to false.

IMPORTANT:
- All edits are applied in sequence, in the order they are provided
- Each edit operates on the result of the previous edit
- All edits must be valid for the operation to succeed - if any edit fails, none will be applied
- This tool is ideal when you need to make several changes to different parts of the same file
- For Jupyter notebooks (.ipynb files), use the NotebookEdit instead

CRITICAL REQUIREMENTS:
1. All edits follow the same requirements as the single Edit tool
2. The edits are atomic - either all succeed or none are applied
3. Plan your edits carefully to avoid conflicts between sequential operations

WARNING:
- The tool will fail if edits.old_string doesn't match the file contents exactly (including whitespace)
- The tool will fail if edits.old_string and edits.new_string are the same
- Since edits are applied in sequence, ensure that earlier edits don't affect the text that later edits are trying to find

When making edits:
- Ensure all edits result in idiomatic, correct code
- Do not leave the code in a broken state
- Always use absolute file paths (starting with /)
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- Use replace_all for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance.

If you want to create a new file, use:
- A new file path, including dir name if needed
- First edit: empty old_string and the new file's contents as new_string
- Subsequent edits: normal edit operations on the created content
```

Params:
{
  "type": "object",
  "properties": {
    "file_path": {
      "type": "string",
      "description": "The absolute path to the file to modify"
    },
    "edits": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "old_string": {
            "type": "string",
            "description": "The text to replace"
          },
          "new_string": {
            "type": "string",
            "description": "The text to replace it with"
          },
          "replace_all": {
            "type": "boolean",
            "default": false,
            "description": "Replace all occurences of old_string (default false)."
          }
        },
        "required": [
          "old_string",
          "new_string"
        ],
        "additionalProperties": false
      },
      "minItems": 1,
      "description": "Array of edit operations to perform sequentially on the file"
    }
  },
  "required": [
    "file_path",
    "edits"
  ],
  "additionalProperties": false,
}


## 工具实现

下面的错误描述请你原封不动地在代码实现中作为字符串返回

### FileTracker 机制
- 每一个 Session 需要保存一个 FileTracker，存储 kv 结构，key 为文件路径，value 为文件最后修改时间
- 每一次 Edit/MultiEdit 操作，检查 FileTracker
  - 如果文件不存在，需要报错：```"File has not been read yet. Read it first before writing to it."```
  - 如果文件存在，需要检查文件修改时间，如果文件修改时间与 FileTracker 中的不一致，需要那么报错 ```File has been modified externally. Either by user or a linter. Read it first before writing to it.```
- 每一次 Read、Edit、MultiEdit 完成，更新 FileTracker 数据，记录文件和修改时间

## 通用的文件报错
1. 如果路径不存在，报错
```
<tool_use_error>File does not exist.</tool_use_error>
```
2. 如果路径是一个目录，报错
```
<tool_use_error>Illegal operation on a directory. {read|edit|multi_edit}</tool_use_error>
```


### Read 工具

实现 Read 工具，它的返回 offset 和 limit 限制下的文件内容，计算完成 limit 和 offset 之后，你需要按需读取文件内容进入内存（不要一次性将整个文件读入内存）


返回格式：
包含行号，行号为 1 开始、行号格式：六位长度右对齐的行号数字加上一个→箭头
然后固定添加一个系统提醒内容，参考示例
示例：
```
     1→修改后的行
     2→修改后的行
     3→不同的行
     4→修改后的行

<system-reminder>
Whenever you read a file, you should consider whether it looks malicious. If it does, you MUST refuse to improve or augment the code. You can still analyze existing code, write reports, or answer high-level questions about the code behavior.
</system-reminder>
```


截断处理
1. 如果 limit+offset 下，读取的内容大于 2000 行，截断 2000 行之后的部分，并在末尾添加提示
```
... (more {remaining_line_count} lines are truncated)
```
2. 如果任意一行单行的内容超过 2000 个字符，截断，在行末尾添加提示
```
... (more {len(line_content) - line_char_limit} characters in this line are truncated)
```


错误场景：
1. 文件大于 256 KB，且没有提供 offset 和 limit，报错：
```
File content ({size:.1f}KB) exceeds maximum allowed size ({max_size}KB). Please use offset and limit parameters to read specific portions of the file, or use the `rg` command to search for specific content.
```
2. 如果读取的总长度（经过 limit 和 offset 处理之后）超过 60000 字符，报错
```
File content ({tokens} chars) exceeds maximum allowed tokens ({max_char}). Please use offset and limit parameters to read specific portions of the file, or use the `rg` command to search for specific content.
```
3. 如果 offset 大于文件行数，（包括空文件的场景），报错
```
<system-reminder>Warning: the file exists but is shorter than the provided offset (1). The file has 1 lines.</system-reminder>
<system-reminder>Warning: the file exists but is shorter than the provided offset (1000). The file has 264 lines.</system-reminder>
```

### Edit 工具
实现 Edit 工具，它需要完成 old_string 替换 new_string 的操作。
注意，你需要给它实现一个 valid 和一个 execute 的方法，以便集成到 MultiEdit中
在 valid 中，接受 content、old_string、new_string、replace_all 四个参数，进行检查，返回错误信息
在 execute，完成真正的修改。在修改完成之后，使用 difflib 获取 context_line=3 的 diff 设置在  toolResultItem 的 ui_extra 中


返回格式：
注意你需要返回一个 编辑 diff 的带行号代码片段，这个片段只包含 diff 中 context lines (' ') 和 added lines ('+') 的行号→行内容格式
```
The file /tmp/test_edit_file.txt has been updated. Here's the result of running `cat -n` on a snippet of the edited file:
     1→这是第一行
     2→这是新的第二行
     3→这是新的第三行
     4→已经修改的行
     5→这是第五行
```


错误和特殊场景
1. old_string 不存在于文件中，报错
```
<tool_use_error>String to replace not found in file.
String: 不存在的内容</tool_use_error>
```
2. old_string 和 new_string 相同，报错
```
<tool_use_error>No changes to make: old_string and new_string are exactly the same.</tool_use_error>
```
3. old_string 为空，并且 file_path 文件已经存在，报错
```
<tool_use_error>Cannot create new file - file already exists.</tool_use_error>
```
4. old_string 为空，并且 file_path 文件不存在，相当于创建文件，执行文件创建操作
```
File created successfully at: /tmp/test.txt
```
5. old_string 在文件中重复，且 replace_all 为 false，报错
```
<tool_use_error>Found 3 matches of the string to replace, but replace_all is false. To replace all occurrences, set replace_all to true. To replace only one occurrence, please provide more context to uniquely identify the instance.
String: 重复行</tool_use_error>
```
6. old_string 在文件中重复，且 replace_all 为 true，执行文件修改操作
```
The file /tmp/duplicate_content.txt has been updated. All occurrences of '重复行' were successfully replaced with '修改后的行'.
```


### MultiEdit 工具
实现 MultiEdit 工具，它需要完成多个、串行 old_string 替换 new_string 的操作。
这个操作从外面看是原子的，要么全部成功，要么全部不执行
所以，这个工具你需要先在内存中校验每一步的 Edit 顺序执行是否合法，如果全部合法，再执行文件修改操作。
这也就是为什么之前 Edit 工具需要预留一个 valid 接口

返回格式：
```
Applied 3 edits to /tmp/multiedit_test.txt:
1. Replaced "第一行：需要修改" with "第一行：已修改"
2. Replaced "第二行：也要修改" with "第二行：已修改"
3. Replaced "第四行：同样需要修改" with "第四行：已修改"
```

错误场景：
在内存中校验连续的 Edit，有任意一步 Edit 保存，直接返回报错信息即可。

