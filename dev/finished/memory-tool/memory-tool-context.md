# Memory Tool Context

**Last Updated: 2025-11-27**

---

## 参考文档

### Claude 官方 Memory Tool 规范

来源: `https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool.md`

#### 工具命令定义

```json
// view - 查看目录或文件
{
  "command": "view",
  "path": "/memories",
  "view_range": [1, 10]  // 可选: 查看特定行范围
}

// create - 创建或覆盖文件
{
  "command": "create",
  "path": "/memories/notes.txt",
  "file_text": "Meeting notes:\n- Discussed project timeline\n"
}

// str_replace - 替换文件中的文本
{
  "command": "str_replace",
  "path": "/memories/preferences.txt",
  "old_str": "Favorite color: blue",
  "new_str": "Favorite color: green"
}

// insert - 在指定行插入文本
{
  "command": "insert",
  "path": "/memories/todo.txt",
  "insert_line": 2,
  "insert_text": "- Review memory tool documentation\n"
}

// delete - 删除文件或目录
{
  "command": "delete",
  "path": "/memories/old_file.txt"
}

// rename - 重命名或移动文件/目录
{
  "command": "rename",
  "old_path": "/memories/draft.txt",
  "new_path": "/memories/final.txt"
}
```

#### 安全要求
- 所有路径必须以 `/memories` 开头
- 使用 `pathlib.Path.resolve()` 和 `relative_to()` 防止路径遍历
- 拒绝 `../`, `..\\`, `%2e%2e%2f` 等遍历模式

---

## 关键文件

### 核心依赖文件

| 文件路径 | 用途 |
|----------|------|
| `src/klaude_code/core/tool/tool_abc.py` | 工具抽象基类 |
| `src/klaude_code/core/tool/tool_registry.py` | 工具注册系统 |
| `src/klaude_code/protocol/tools.py` | 工具名称常量 |
| `src/klaude_code/protocol/model.py` | ToolResultItem 等数据模型 |
| `src/klaude_code/protocol/llm_parameter.py` | ToolSchema 定义 |

### 参考实现文件

| 文件路径 | 参考价值 |
|----------|----------|
| `src/klaude_code/core/tool/edit_tool.py` | 文件写入模式、错误处理 |
| `src/klaude_code/core/tool/read_tool.py` | 文件读取、行号格式化 |
| `src/klaude_code/core/tool/bash_tool.py` | 参数验证、Pydantic 模型 |

---

## 设计决策记录

### D1: 路径虚拟化设计
**决策**: 使用 `/memories` 作为虚拟根路径
**理由**: 
- 与 Claude 官方规范一致
- 隐藏实际文件系统路径
- 便于路径安全验证

**映射规则**:
```
/memories          → <git_root>/.claude/memories/
/memories/foo.txt  → <git_root>/.claude/memories/foo.txt
```

### D2: Git 根目录检测
**决策**: 使用 `git rev-parse --show-toplevel` 获取 Git 根目录
**Fallback**: 如果不在 Git 仓库中，使用当前工作目录
**理由**: 
- 与现有代码库约定一致
- `.claude/` 目录通常在项目根目录

### D3: 参数模式选择
**决策**: 使用 `command` 字段区分操作，而非多个工具
**理由**:
- 与 Claude 官方规范一致
- 减少工具数量
- 更好的语义分组

---

## 技术细节

### ToolABC 接口

```python
class ToolABC(ABC):
    @classmethod
    @abstractmethod
    def schema(cls) -> ToolSchema:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        raise NotImplementedError
```

### ToolSchema 结构

```python
ToolSchema(
    name="Memory",
    type="function",
    description="...",
    parameters={
        "type": "object",
        "properties": {...},
        "required": [...],
        "additionalProperties": False,
    },
)
```

### ToolResultItem 结构

```python
ToolResultItem(
    status="success" | "error",
    output="...",
    ui_extra=None,  # 可选 UI 扩展
)
```

---

## 测试用例设计

### 功能测试

```python
# view 命令
- test_view_directory_listing
- test_view_file_content
- test_view_with_range
- test_view_nonexistent_path

# create 命令
- test_create_new_file
- test_create_overwrite_file
- test_create_with_nested_directory

# str_replace 命令
- test_str_replace_success
- test_str_replace_file_not_found
- test_str_replace_string_not_found

# insert 命令
- test_insert_at_line
- test_insert_at_end
- test_insert_in_empty_file

# delete 命令
- test_delete_file
- test_delete_directory
- test_delete_nonexistent

# rename 命令
- test_rename_file
- test_rename_directory
- test_rename_cross_directory
```

### 安全测试

```python
- test_path_traversal_dotdot
- test_path_traversal_encoded
- test_path_outside_memories
- test_absolute_path_rejected
```
