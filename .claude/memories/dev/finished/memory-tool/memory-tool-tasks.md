# Memory Tool Tasks Checklist

**Last Updated: 2025-11-27**

---

## Phase 1: 基础架构

- [x] **1.1** 在 `protocol/tools.py` 添加 `MEMORY = "Memory"` 常量
- [x] **1.2** 创建 `memory_tool.py` 基础结构
  - [x] 定义 MemoryTool 类继承 ToolABC
  - [x] 定义 MemoryArguments Pydantic 模型
  - [x] 实现 schema() 方法
- [x] **1.3** 实现路径安全验证
  - [x] _get_memories_root() - 获取实际 memories 目录
  - [x] _validate_path() - 验证路径安全性
  - [x] 处理 ../ 遍历攻击
  - [x] 处理 URL 编码攻击
- [x] **1.4** 实现目录自动创建

## Phase 2: 核心命令实现

- [x] **2.1** 实现 `view` 命令
  - [x] 目录列表功能
  - [x] 文件内容查看
  - [x] view_range 分页支持
- [x] **2.2** 实现 `create` 命令
  - [x] 文件创建
  - [x] 父目录自动创建
  - [x] 覆盖已存在文件
- [x] **2.3** 实现 `str_replace` 命令
  - [x] 文本替换
  - [x] 错误处理 (文件不存在、字符串不存在)
- [x] **2.4** 实现 `insert` 命令
  - [x] 行插入
  - [x] 边界情况处理
- [x] **2.5** 实现 `delete` 命令
  - [x] 文件删除
  - [x] 目录递归删除
- [x] **2.6** 实现 `rename` 命令
  - [x] 文件/目录重命名
  - [x] 跨目录移动

## Phase 3: 集成和注册

- [x] **3.1** 在 `__init__.py` 添加 MemoryTool 导入
- [x] **3.2** 在 `get_main_agent_tools()` 添加 Memory 工具
- [ ] **3.3** (可选) 添加系统提示指导

## Phase 4: 测试

- [x] **4.1** 编写功能单元测试
  - [x] view 命令测试
  - [x] create 命令测试
  - [x] str_replace 命令测试
  - [x] insert 命令测试
  - [x] delete 命令测试
  - [x] rename 命令测试
- [x] **4.2** 编写安全测试
  - [x] 路径遍历防护测试
  - [x] 路径验证测试

---

## 进度追踪

| Phase | 状态 | 进度 |
|-------|------|------|
| Phase 1 | Completed | 100% |
| Phase 2 | Completed | 100% |
| Phase 3 | Completed | 100% |
| Phase 4 | Completed | 100% |

**Overall Progress**: 100%
