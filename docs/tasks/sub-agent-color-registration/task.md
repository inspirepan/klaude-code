# 子代理颜色注册修复

## 已确认方案

1. 快照只增加三个可选 `parent_tool_batch_*` 字段；不保存完整 prompt 或 SubAgentState。
2. launcher → task manager → 快照保留批次关联；旧快照缺字段时默认 None。
3. renderer 幂等注册：颜色只分配一次，补全元数据不清除已有字段，state=None 不降级子代理。
4. Launch、初始化状态与 TaskStart 共用已有 batch 配色映射；保留逆序启动和隐藏嵌套 Launch 的颜色预留。
5. 运行中任务缺 session ID 时保留后台任务记录，暂不显示子代理行；终态无 ID 的失败报告仍可显示。

## 当前进度

- 实现完成：protocol/background_task.py、agent/runtime/{sub_agent,task_manager}.py、tui/{machine,renderer}.py。
- renderer 的快照和持久化报告复用 `_register_background_agent`，最终均进入 `register_session`；未新增注册框架。
- 已覆盖真实 launcher → task manager → 初始化快照 → TaskStart → 流式响应 → 重复 TaskStart 的颜色稳定，以及批次元数据落盘恢复。
- 已覆盖 compact/full、快照先到/TaskStart 先到、逆序批次、稀疏注册、无 ID 运行任务和旧持久化兼容；原嵌套颜色预留测试保留。

## 已运行验证

- `uv run pytest tests/tui/test_renderer_bottom_live.py tests/tui/test_tui_machine_sub_agent_status.py tests/tui/test_shared_tasks.py tests/tui/test_async_task_transcript.py tests/agent/test_sub_agent_registry.py tests/agent/test_background_tasks.py -x -q --tb=short`：247 passed。
- 9 个变更 Python 文件的 `uv run ruff format`、`uv run ruff check`、`uv run ty check`：通过。
- `make imports`：通过，1 个架构契约保持。
- `make format`、`make lint`：被本地 `src/klaude_code/skill/assets/image-gen/scripts/image_gen.py` 的 75 个既有 Ruff 错误阻塞；全仓格式化未完成。
- `make typecheck imports`：typecheck 被 skill/assets 中 16 个诊断阻塞，包括 image-gen 未定义引用及 PDF 可选依赖缺失；随后单独运行 `make imports` 通过。
- 主 agent 独立复跑上述 247 项测试：全部通过；正确性与可维护性审查均未发现需修复问题。
- 提交前运行 `make pre-push`：format 阶段因上述 75 个既有 Ruff 错误失败，后续 lint、全量测试和构建未执行；按仓库规则未推送。

## 交接与剩余验证

- 实现与代码审查完成；本次修复单独提交，推送被 `make pre-push` 阻塞。
- 未运行真实终端或全局安装环境的人工 UI smoke test；未运行全量测试或构建。
- 旧快照缺批次信息时仍可加载，不能据此还原从未收到的 Launch 批次关联；已有颜色不会因后续注册而改变。