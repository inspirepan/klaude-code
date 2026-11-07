# 全库结构整理

## 已确认

1. 用户授权全库重构，同时清理复述代码的注释和低价值测试。
2. 保留现有行为、持久化格式、provider 差异及分层约束；测试清理放在结构调整之后。
3. 用户已授权将本轮改动作为一个提交保存；不推送。

## 问题与方案

1. 认证 JSON 的读取、写入和空文件删除由 auth 包统一实现。
   - `auth/base.py:51`、`auth/env.py:9`、`auth/removed_provider.py:32` 重复实现同一文件格式。
   - `tests/conftest.py:75` 同时覆盖 base/env 两份路径常量，反映路径来源的隐含同步要求。
   - 保留各调用者现有锁和异常策略，不扩展并发机制。
2. 会话元数据共用 JSON 读取与时间戳解析。
   - `session/meta.py:56`、`session/store.py:71`、`app/session_index.py:18` 重复读取 JSON 对象。
   - `session/meta.py:208` 与 `app/session_index.py:67` 的时间戳容错不同，索引可显示的记录可能无法恢复。
   - 摘要和完整会话保留各自数据形状，不让索引解析完整历史状态。
3. OpenAI Compatible / OpenRouter 共用 Chat Completions 请求和流封装。
   - 两个 `client.py` 重复请求、错误转换、日志和流初始化。
   - 保留独立 payload、headers、reasoning handler、timeout 和 provider prefix；不统一其他 provider。
4. TUI 命令只维护一份有序清单。
   - `tui/command/__init__.py:34` 与 `:81` 分别维护注册和惰性访问清单。
   - 加载标志提前设置，导入失败后无法正常再次初始化。
5. 删除确认无生产调用者的遗留接口和 Web 组件。
   - `skill/loader.py` 的私有旧别名、`get_skills_yaml()` 只保留兼容包装；另确认 `_find_git_repo_root` 实例方法没有调用者。XML 旧持久化格式解析仍有真实用途。
   - `web/src/ui-primitives/Input.tsx` 只有 barrel 导出，没有消费点；Web 包为 private。
   - 复查确认 `agent/task.py:1027` 的附件重置函数仅透传到 `attachments/state.py`；调用者和测试直接使用拥有实现的模块。
6. 最后清理测试与注释。
   - 删除只证明旧别名等价的测试。
   - 复核 characterization 测试，以真实行为与现有覆盖决定是否改写；文件名和私有函数调用本身不构成删除理由。
   - 删除改动范围内复述实现和过时的注释，保留外部约束、磁盘兼容及并发原因。

## 审查排除项

1. CLI 使用 TUI 选择器、主题符合既有 `cli > tui` 方向，未证实移动有收益。
2. agent 和 shell 共用 tool 快照写入符合既有分层，不能据此认定倒置。
3. 按 ID 查找隐藏旧子会话、跨进程新记录的磁盘回退有现存需求，保留。
4. provider 协议差异、inclusive Usage 计数、旧会话 XML/队列格式兼容及安全测试有实际用途，保留。

## 当前阶段与验证

1. 全库分区只读审查完成；另补查 agent/tool/control。
2. 基线 `make test`：3844 passed、1 skipped、4 deselected。
3. 六组结构调整已落地；路径 patch 迁到唯一的 `auth.base.KLAUDE_AUTH_FILE`。
4. 针对性验证：auth/app/config/TUI/CLI 认证 262 passed；LLM 456 passed；命令 263 passed；会话/app/server 排除尚未迁移的认证测试时 318 passed，新时间戳回归 12 passed。认证迁移已完成，最终全量已重新覆盖。
5. Web：`pnpm test` 157 passed，`pnpm typecheck` 通过；存在既有 React `act` 弃用警告。
6. 测试清理：删除旧 skill 别名等价测试；两个压缩测试改查公开 token 结果；fallback 用工具保留结果替代强制新对象身份；保留 TUI 命令顺序和安全测试。
7. 注释清理覆盖改动范围，保留外部约束、锁、持久化兼容原因。Web 无用组件与样式已移至废纸篓，可恢复。
8. 二次结构检查未发现新的高价值问题；附件重置透传包装经直接核验后删除，测试改从拥有实现的模块导入。
9. `make format`、`make lint` 通过，导入分层检查 364 files / 1620 dependencies，无违规。
10. 最终 `make test`：3877 passed、1 skipped、4 deselected（排除网络测试）。
11. `make build` 通过，Web、wheel、sdist 及发行包 Web 资源验证均通过；有 Vite 大 chunk 警告。
12. `uv run klaude --help` 启动冒烟通过。未运行网络服务调用或真实终端手工验证。
13. 独立正确性与维护性审查均无发现；正确性审查额外运行边界回归 82 passed。

## 交接

1. 本轮清单已完成，已运行的自动验证全部通过；没有待处理的审查问题。
2. 本轮代码、测试和验证记录纳入同一提交，不推送。
3. 外部 provider 联机调用与真实交互终端未验证；发布需用户另行授权。