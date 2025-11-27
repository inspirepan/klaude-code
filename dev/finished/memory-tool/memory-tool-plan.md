# Memory Tool Implementation Plan

**Last Updated: 2025-11-27**

---

## Executive Summary

本计划旨在为 Klaude Code 添加一个 Memory Tool，使 Agent 能够在会话之间持久化存储和检索信息。该工具将参考 Claude 官方的 Memory Tool 设计，但不使用 Claude API 的 `context-management-2025-06-27` beta 功能，而是实现为一个标准的客户端工具，以支持多种 LLM 模型。

### 核心价值
- 跨会话持久化：Agent 可以在多次执行之间保持项目上下文
- 知识积累：随时间学习和记录决策、偏好、经验教训
- 工作流中断恢复：在上下文窗口重置时保留关键进度信息

### 设计原则
- 兼容性：适配非 Claude 模型，作为标准 function tool 实现
- 安全性：路径遍历保护，限制操作在指定目录内
- 简洁性：与现有工具系统保持一致的实现模式

---

## Current State Analysis

### 现有工具系统架构

```
src/klaude_code/
├── core/tool/
│   ├── tool_abc.py          # 抽象基类 ToolABC
│   ├── tool_registry.py     # 工具注册系统 (@register 装饰器)
│   ├── tool_runner.py       # 工具执行入口
│   ├── tool_context.py      # 会话上下文 (current_session_var)
│   ├── edit_tool.py         # 文件编辑工具 (参考实现)
│   ├── read_tool.py         # 文件读取工具 (参考实现)
│   └── ...
├── protocol/
│   ├── tools.py             # 工具名称常量定义
│   └── model.py             # ToolResultItem 等数据结构
└── config/
    └── constants.py         # 配置常量
```

### 工具实现模式
每个工具都遵循以下模式：
1. 在 `protocol/tools.py` 中定义工具名常量
2. 创建 `*_tool.py` 文件，继承 `ToolABC`
3. 使用 `@register(TOOL_NAME)` 装饰器注册
4. 实现 `schema()` 和 `call()` 方法
5. 在 `__init__.py` 中导入以触发注册
6. 在 `tool_registry.py` 的 `get_main_agent_tools()` 中添加

### Memory 存储位置
- 默认目录：`<git_root>/.claude/memories/`
- 符合 Claude Code 的配置目录约定

---

## Proposed Future State

### Memory Tool 功能概览

Memory Tool 将提供 6 个子命令，完全对齐 Claude 官方规范：

| 命令 | 功能 | 参数 |
|------|------|------|
| `view` | 查看目录内容或文件内容 | path, view_range (可选) |
| `create` | 创建或覆盖文件 | path, file_text |
| `str_replace` | 替换文件中的文本 | path, old_str, new_str |
| `insert` | 在指定行插入文本 | path, insert_line, insert_text |
| `delete` | 删除文件或目录 | path |
| `rename` | 重命名/移动文件或目录 | old_path, new_path |

### 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                      MemoryTool                              │
├─────────────────────────────────────────────────────────────┤
│  schema()   → ToolSchema with command-based parameters      │
│  call()     → Dispatch to command handlers                  │
├─────────────────────────────────────────────────────────────┤
│  Commands:                                                   │
│  ├── _view()       → List dir or read file with line range │
│  ├── _create()     → Write new file                         │
│  ├── _str_replace()→ Replace text in file                   │
│  ├── _insert()     → Insert text at line                    │
│  ├── _delete()     → Delete file/directory                  │
│  └── _rename()     → Rename/move file/directory             │
├─────────────────────────────────────────────────────────────┤
│  Security:                                                   │
│  └── _validate_path() → Ensure path within memories dir     │
└─────────────────────────────────────────────────────────────┘
```

### 路径安全策略
- 所有路径必须以 `/memories` 开头（虚拟根路径）
- 实际映射到 `<git_root>/.claude/memories/`
- 使用 `pathlib.Path.resolve()` 防止 `../` 遍历攻击
- 拒绝 URL 编码的遍历序列

---

## Implementation Phases

### Phase 1: 基础架构 (Effort: M)

**目标**: 建立工具基础结构和路径安全机制

1.1 在 `protocol/tools.py` 添加常量 `MEMORY = "Memory"`
1.2 创建 `memory_tool.py` 基础结构
1.3 实现路径验证和安全检查
1.4 实现 memories 目录自动创建

### Phase 2: 核心命令实现 (Effort: L)

**目标**: 实现 6 个子命令

2.1 实现 `view` 命令 - 目录列表和文件查看
2.2 实现 `create` 命令 - 文件创建
2.3 实现 `str_replace` 命令 - 文本替换
2.4 实现 `insert` 命令 - 行插入
2.5 实现 `delete` 命令 - 文件/目录删除
2.6 实现 `rename` 命令 - 重命名/移动

### Phase 3: 集成和注册 (Effort: S)

**目标**: 将 Memory Tool 集成到主 Agent 工具集

3.1 在 `__init__.py` 中导入 MemoryTool
3.2 在 `tool_registry.py` 的 `get_main_agent_tools()` 中添加
3.3 添加 Memory Tool 的系统提示指导

### Phase 4: 测试 (Effort: M)

**目标**: 确保工具稳定可靠

4.1 单元测试 - 各命令功能
4.2 安全测试 - 路径遍历防护
4.3 集成测试 - 与 Agent 协作

---

## Detailed Tasks

### Phase 1: 基础架构

#### Task 1.1: 添加工具名常量
- **文件**: `src/klaude_code/protocol/tools.py`
- **操作**: 添加 `MEMORY = "Memory"`
- **Effort**: S
- **验收标准**: 常量定义存在且可导入

#### Task 1.2: 创建 memory_tool.py 基础结构
- **文件**: `src/klaude_code/core/tool/memory_tool.py`
- **操作**: 
  - 创建 `MemoryTool` 类继承 `ToolABC`
  - 定义 Pydantic 参数模型
  - 实现 `schema()` 方法
- **Effort**: M
- **依赖**: Task 1.1
- **验收标准**: 
  - 类正确继承 ToolABC
  - schema() 返回正确的 ToolSchema
  - 参数模型覆盖所有 6 个命令

#### Task 1.3: 实现路径安全验证
- **文件**: `src/klaude_code/core/tool/memory_tool.py`
- **操作**:
  - 实现 `_get_memories_root()` 获取实际目录路径
  - 实现 `_validate_path()` 验证路径安全
  - 处理 `../` 遍历、URL 编码等攻击向量
- **Effort**: M
- **验收标准**:
  - `/memories/test.txt` 正确映射到 `<git>/.claude/memories/test.txt`
  - `/memories/../etc/passwd` 被拒绝
  - `%2e%2e%2f` 编码被拒绝

#### Task 1.4: 实现目录自动创建
- **文件**: `src/klaude_code/core/tool/memory_tool.py`
- **操作**: 在首次操作时自动创建 `.claude/memories/` 目录
- **Effort**: S
- **验收标准**: 目录不存在时自动创建

### Phase 2: 核心命令实现

#### Task 2.1: 实现 view 命令
- **操作**:
  - 目录: 返回文件/子目录列表
  - 文件: 返回内容，支持 view_range 分页
- **Effort**: M
- **验收标准**:
  - 目录返回格式: `Directory: /memories\n- file1.txt\n- file2.txt`
  - 文件返回内容带行号
  - view_range [1, 10] 只返回 1-10 行

#### Task 2.2: 实现 create 命令
- **操作**: 创建新文件，父目录不存在时自动创建
- **Effort**: S
- **验收标准**:
  - 文件成功创建
  - 父目录自动创建
  - 已存在文件被覆盖

#### Task 2.3: 实现 str_replace 命令
- **操作**: 在文件中替换文本
- **Effort**: S
- **验收标准**:
  - 精确替换第一个匹配
  - 文件不存在时报错
  - old_str 不存在时报错

#### Task 2.4: 实现 insert 命令
- **操作**: 在指定行插入文本
- **Effort**: S
- **验收标准**:
  - 正确在指定行插入
  - 处理行号超出范围的情况
  - 处理空文件

#### Task 2.5: 实现 delete 命令
- **操作**: 删除文件或目录
- **Effort**: S
- **验收标准**:
  - 文件删除成功
  - 目录递归删除成功
  - 不存在时报错

#### Task 2.6: 实现 rename 命令
- **操作**: 重命名/移动文件或目录
- **Effort**: S
- **验收标准**:
  - 重命名成功
  - 跨目录移动成功
  - 目标已存在时报错

### Phase 3: 集成和注册

#### Task 3.1: 在 __init__.py 中导入
- **文件**: `src/klaude_code/core/tool/__init__.py`
- **操作**: 添加 `from .memory_tool import MemoryTool`
- **Effort**: S
- **验收标准**: 导入成功，工具注册到 registry

#### Task 3.2: 在 get_main_agent_tools 中添加
- **文件**: `src/klaude_code/core/tool/tool_registry.py`
- **操作**: 在工具列表中添加 `tools.MEMORY`
- **Effort**: S
- **验收标准**: 所有模型的 main agent 都包含 Memory 工具

#### Task 3.3: 添加系统提示指导 (可选)
- **文件**: 提示相关文件
- **操作**: 添加 Memory Tool 使用指导
- **Effort**: S
- **验收标准**: Agent 知道如何使用 Memory 工具

### Phase 4: 测试

#### Task 4.1: 单元测试
- **文件**: `tests/test_memory_tool.py`
- **Effort**: M
- **验收标准**: 所有命令功能测试通过

#### Task 4.2: 安全测试
- **文件**: `tests/test_memory_tool.py`
- **Effort**: M
- **验收标准**: 路径遍历攻击被正确拦截

---

## Risk Assessment and Mitigation

| 风险 | 影响 | 可能性 | 缓解措施 |
|------|------|--------|----------|
| 路径遍历漏洞 | 高 | 中 | 使用 pathlib 的 resolve() 和 relative_to() 验证 |
| Git 根目录检测失败 | 中 | 低 | 提供 fallback 到当前目录 |
| 大文件读取性能问题 | 低 | 低 | 实现 view_range 分页 |
| 与现有 Read/Edit 工具功能重叠 | 低 | 低 | Memory 限制在 /memories 目录内 |

---

## Success Metrics

1. **功能完整性**: 6 个命令全部实现且通过测试
2. **安全性**: 所有路径遍历测试用例通过
3. **兼容性**: 在 Claude, GPT-4, Gemini 等模型上正常工作
4. **用户体验**: Agent 能自然地使用 Memory 工具进行跨会话记忆

---

## Required Resources and Dependencies

### 无需新依赖
- 使用 Python 标准库: `pathlib`, `os`, `shutil`
- 使用已有依赖: `pydantic`

### 文件变更清单
1. `src/klaude_code/protocol/tools.py` - 添加常量
2. `src/klaude_code/core/tool/memory_tool.py` - 新建 (主要文件)
3. `src/klaude_code/core/tool/__init__.py` - 添加导入
4. `src/klaude_code/core/tool/tool_registry.py` - 添加到工具列表
5. `tests/test_memory_tool.py` - 新建测试
