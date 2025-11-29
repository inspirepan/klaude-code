# User Input 文本+图片载体改造 - 任务清单

Last Updated: 2025-11-29 (Phase 4 Completed)

> 勾选顺序建议按 Phase 从上到下推进；如需调整顺序，请在 comment 中注明原因。

## Phase 0：设计与对齐 ✅

- [x] 0.1 确认 `UserInputPayload` 的命名与字段
- [x] 0.2 确认 `UserInputPayload` 放在 `protocol/model.py` 并在实现中保持这一约定
- [x] 0.3 与主要维护者对齐"一次性切换到 UserInputPayload 并移除 clipboard manifest + clipboard_image_reminder"的改造范围

## Phase 1：协议与核心模型改造 ✅

- [x] 1.1 在 `protocol/model.py` 中新增 `UserInputPayload` 类型
- [x] 1.2 为 `UserMessageEvent` 增加 `images` 字段（`protocol/events.py`）
- [x] 1.3 将 `UserInputOperation` 从 `content: str` 改为 `input: UserInputPayload`（`protocol/op.py`）
- [x] 1.4 确保所有构造 `UserInputOperation` 的代码编译通过并通过基础测试

## Phase 2：Executor / Agent / Task 链路适配 ✅

- [x] 2.1 在 `ExecutorContext.handle_user_input` 中使用 `operation.input: UserInputPayload` 作为唯一来源
- [x] 2.2 `handle_user_input` 写入 `UserMessageEvent` 时附带 `images`
- [x] 2.3 `handle_user_input` 在追加历史时使用 `UserMessageItem(content, images)`
- [x] 2.4 将 `_run_agent_task` 签名改为只接受 `UserInputPayload`
- [x] 2.5 将 `Agent.run_task` 签名改为只接受 `UserInputPayload`
- [x] 2.6 将 `TaskExecutor.run` 签名改为只接受 `UserInputPayload`
- [x] 2.7 为上述改造补充/更新单元测试

## Phase 3：UI 输入层（REPL）改造 ✅

- [x] 3.1 将 `InputProviderABC.iter_inputs` 的类型改为 `AsyncIterator[UserInputPayload]`
- [x] 3.2 检查其他 `InputProvider` 实现（如有）并更新
- [x] 3.3 改造 `ClipboardCaptureState` 以不再依赖 manifest 写入，只维护"tag → 图片路径"的内存映射
- [x] 3.4 在 `Enter` 提交逻辑中直接构造 `UserInputPayload(text, images)`，其中 `images` 基于当前 buffer 中出现的 `[Image #N]` tag 决定
- [x] 3.5 去除 `persist_clipboard_manifest` 的调用
- [x] 3.6 `run_interactive` 适配新的 `UserInputPayload`（构造 `UserInputOperation` 时带上 `input=payload`）
- [x] 3.7 `run_exec` 内部统一构造 `UserInputPayload(text=input_content, images=None)`，再构造 `UserInputOperation`

## Phase 4：reminders 与 clipboard_manifest 清理 ✅

- [x] 4.1 删除 `clipboard_image_reminder` 实现，并从 `ALL_REMINDERS` / `load_agent_reminders` 中移除其注册
- [x] 4.2 删除 `clipboard_manifest.py` 文件及其所有引用（包括 `ClipboardManifest*` 类型）
- [x] 4.3 删除 `tests/test_clipboard_manifest.py` 及任何直接测试 manifest 的用例
- [x] 4.4 全局搜索并移除对 `persist_clipboard_manifest` / `load_latest_clipboard_manifest` 的残余引用
- [x] 4.5 跑完整测试（含 pytest 和 pyright），确保删除操作未引入运行时或类型错误

## Phase 5：测试与回归

- [ ] 5.1 为 Executor/Agent/Task 添加针对 `UserInputPayload` 的单元测试
- [ ] 5.2 为 REPL 粘贴图片场景添加集成测试/手动脚本
- [ ] 5.3 验证不再生成新的 `~/.klaude/clipboard/manifests/manifest-*.json` 文件
- [ ] 5.4 验证纯文本对话场景行为未发生回归
- [ ] 5.5 验证历史会话回放中，带图片的 user message 能正确展示

## Phase 6：收尾与文档

- [ ] 6.1 在项目文档/开发者指南中补充用户输入图片链路的最新设计
- [ ] 6.2 如有需要，在发布说明中注明该改动（尤其是对外 API 影响）
- [ ] 6.3 总结本次改造的经验教训与后续可迭代点
