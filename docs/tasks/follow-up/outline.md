# Follow-up

## 已确认

1. `Enter` 保持 steering，在安全步骤边界注入。
2. `Alt+Enter` 提交 follow-up；agent 本来要自然结束时逐条消费，在同一个 run 内继续。
3. 两类输入独立排队、持久化和显示；空闲时提交正常启动运行。
4. 保留现有 steering 的历史磁盘键 `follow_up_queue` 和协议值；新 follow-up 使用独立名称。
5. 空输入按 `↑` 或 `Alt+↑` 一次取回两队列全部消息；steering 在前、follow-up 在后，用空行合并。重新提交由 `Enter` / `Alt+Enter` 决定类型，不加选择器，Esc 保持现状。

## 实现约定

- TUI 提交标记：`UserInputPayload.delivery`，值为 `steering` 或 `follow_up`，默认 `steering`；只用于本地路由，不序列化。
- 新操作：`QueueFollowUpOperation`，协议值 `queue_follow_up`。
- 新事件：`FollowUpQueueChangedEvent`，携带 `texts`。
- 新持久化键：`pending_follow_ups`；内存属性为 `follow_up_queue`。
- Agent 提供 `follow_up()`、`follow_up_snapshot()`、`pop_all_follow_up()`；自然结束消费回调与步骤注入分开。

## 阶段与验证

1. 已完成：检查当前运行边界、队列持久化、输入绑定及 pi 的消费方式。
2. 已完成：harness 双队列、自然结束消费与 TUI 提交、显示；消费顺序、同 run 继续、恢复、取消与按键路由已有测试。
3. 已完成：格式化、静态检查、完整测试及独立正确性和维护性审查；修正 Esc 后误跑 follow-up 的边界并复验。
4. 已完成：统一取回两队列，按 pi 用空行合并编辑；取回顺序、两队列清空及落盘、排除已开始消费的输入、重新提交类型和 Esc 行为均已测试。

## 交接

- 本轮授权提交 follow-up 与双队列编辑改动；未授权推送。
- TUI：两队列独立显示；`↑` / `Alt+↑` 统一取回编辑；`Alt+↑` 保留接上已有草稿的行为，显式手动分割仍可用。
- 后端：相关测试范围 1048 passed。
- 整体验证：`make lint`、`uv run ruff format --check .` 通过；初次 `make test` 为 3785 passed、1 skipped、4 deselected。
- 审查修正：Esc 保留 follow-up，仍允许原有 steering 继续；主动提交新任务后再消费 follow-up。相关测试 126 passed，最终完整测试为 3787 passed、1 skipped、4 deselected。
- 按键验证使用 prompt-toolkit 输入管道，覆盖传统 ESC+CR 和 CSI-u；未做真实终端手工验证。
- 统一取回验证：相关三个测试文件 205 passed；`make lint`、`uv run ruff format --check .` 通过；全量非网络测试 3795 passed、1 skipped、4 deselected；独立正确性审查未发现问题。
- 状态：实现与自动验证完成，未推送。