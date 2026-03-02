# Phase 2 实施计划：输入通道会话化（RuntimeHub + SessionRuntime）

目标：把输入调度从“单 submission loop”逐步迁移到“按 session mailbox 路由”，同时保持每次改动后可运行。

---

## 1. 当前增量（已完成）

本次已落地最小骨架：

- 新增 `RuntimeHub`：`src/klaude_code/core/runtime_hub.py`
- 新增 `SessionRuntime`：`src/klaude_code/core/session_runtime.py`
- `Executor.start()` 中，非 EndOperation 的 submission 改为交由 `RuntimeHub.submit(...)`
- `RuntimeHub` 为每个 session 建立独立 mailbox + worker

这一步完成后，系统仍可运行，且输入路由路径已经具备“按 session 分桶”的结构。

---

## 2. 本阶段仍保留的临时实现

> 这些临时项都已在 `migration-gap-register.md` 登记。

- ingress 仍从 `Executor.submission_queue` 进入（RuntimeHub 在其后层）
- SessionRuntime worker 共享全局 execution lock（为兼容当前单 `_agent` 运行态）
- SessionRuntime 目前只承载 mailbox/worker，不承载会话状态（pending/config/active_root_task）

---

## 3. 后续子步骤（Phase 2 内）

1. 将会话级运行态逐步迁入 SessionRuntime（先 `active_root_task`）
2. 把 busy/reject 语义前移到 SessionRuntime gate
3. 逐步降低对全局 execution lock 的依赖

---

## 4. 验收要点（当前增量）

- 不破坏现有 CLI/TUI 主流程
- 同一 session 的操作在其 mailbox 内保持顺序
- global interrupt 仍可处理（映射到 global runtime）

对应测试：`tests/test_runtime_hub.py`
