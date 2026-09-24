# Server 更新与优雅重启：调研 handoff

## 背景与结论

Klaude 的交互 TUI 是独立 server 的客户端。退出 TUI 不会退出或重启 server；安装新代码也不等于 server 已运行新代码。当前自动 Git 升级会尝试对空闲 server 执行一次非强制 reload，但 server 忙碌时只返回 pending，不会在稍后空闲时自行重试。因此，TUI 的“自动升级成功”通知只能表示安装完成，不能表示 server 已切换到新代码。

本文件记录 `../coding-agent/` 下其他项目的源码调查，以及基于调查做出的设计决定。文末「已实施」一节描述当前代码的实际行为；其上的「现在的真实行为」是实施前的快照，保留作对照。以下路径以本仓库根目录为起点，行号对应调研时的 checkout，后续可用路径和符号重新定位。

## 项目对照

| 项目 | 常驻进程更新策略 | 在途任务 / 恢复边界 | 可借鉴点 |
| --- | --- | --- | --- |
| Hermes | gateway 接到 restart 请求即拒绝新任务，等待已有 work；随后关闭并由 supervisor 或 detached helper 重启 | 等待有期限；超时进入 stop/drain，可能中断任务。提前标记 `resume_pending`，完成后验证运行版本 | server 自己持有 drain 状态，而不是客户端反复尝试空闲 reload |
| Grok | 客户端发送 `RelaunchForUpdate`；Leader 确认并排空、flush、退出；后续 `connect_or_spawn` 的客户端在锁下拉起替代进程 | 最多等待 busy work 5 秒，flush 最多 5 秒；超时的 turn 从最后持久化边界恢复，非无中断热替换 | 控制协议先 ACK 再关闭；重启请求去重；明确规定谁拉起新进程 |
| OpenAI Codex | updater 在发布/校验安装后比较二进制身份和版本，再管理 app-server 的停止与拉起 | 进程级 grace 超时后强制终止；未找到按 agent turn 排空的保证 | 独立进程负责安装与服务生命周期，确认 readiness；不适合照搬其超时强杀策略 |
| Claude Code | 常规自动更新后在 REPL 显示 `Restart to apply` | 当前 checkout 可见 daemon 入口，但缺少 daemon 实现，不能据此断言其服务重启语义 | 把“已安装”和“运行中进程已更新”分开表述 |
| OpenCode | `serve` 启动长驻 server，提供 stop；未找到更新后自动重启和 active-turn drain 的串联流程 | stop 是关闭 listener/scope，不等于等待 agent turn 完成 | 不要将 HTTP server 的 graceful shutdown 等同任务排空 |
| Pi / Kimi / DeepSeek Harness | 常规 CLI 不依赖 Klaude 式共享常驻会话 server；Pi 另有实验性 server，Kimi 有扩展/runtime，Harness 有关闭控制器 | 各有会话持久化、关闭或插件/配置重载；未找到与 Klaude 同构的升级交接 | 会话可恢复不代表重启后原 turn 不间断 |

### 外部源码入口

- Hermes：`../coding-agent/hermes-agent/gateway/run_shutdown.py:1550` 的 `_await_active_work_before_restart`，`:1609` 的 `request_restart`（设置 `_draining`、拒绝新 turn），`:1783` 的提前标记及 drain；`gateway/restart.py:12` 定义 supervisor 重启退出码；`gateway/status.py:687` 报告运行代码。更新器的服务编排见 `hermes_cli/update_cmd.py:1500`、`website/docs/reference/cli-commands.md:1952`。
- Grok：`../coding-agent/xai-org-grok-build/crates/codegen/xai-grok-shell/src/leader/server.rs:1392` 的等待和 flush 上限，`:1403` 的版本检查/重复请求保护，`:1439` 的 drain；`src/leader/mod.rs:1096` 的让位说明、`:1459` 的 `connect_or_spawn`、`:1626` 的 spawn；更新客户端入口在 `crates/codegen/xai-grok-pager-bin/src/main.rs:2764`。这里确认由后续客户端拉起 Leader，不是 Leader 自行 exec 或独立 supervisor。
- Codex：`../coding-agent/openai-codex/codex-rs/app-server-daemon/src/update_loop.rs:398` 决定重启模式、`:419` 重试忙碌的 lifecycle lock；`src/backend/pid.rs:162` 的停机宽限与强制终止；`src/prepare_install.rs:223` 的安装校验/发布。这里没有证据证明它会等 agent turn 自然结束。
- Claude Code：`../coding-agent/claude-code/src/components/AutoUpdater.tsx:163` 的周期检查及 `:187` 的重启提示；`src/entrypoints/cli.tsx:95` 可见 daemon 入口，但当前检出的 `src/daemon/` 不存在，不能作为 daemon reload 的依据。
- OpenCode：`../coding-agent/anomalyco-opencode/packages/opencode/src/cli/cmd/serve.ts:6` 的长驻 serve；`packages/opencode/src/server/server.ts:172` 的 listen/stop。
- Pi：`../coding-agent/badlogic-pi-mono/packages/coding-agent/src/cli.ts:1` 的 CLI，`packages/coding-agent/src/experimental/server.ts:144` 的实验性 server；Kimi：`../coding-agent/MoonshotAI-kimi-code/apps/vscode/src/runtime/kimi-runtime.ts:87` 的 session 恢复、`:258` 的关闭；Harness：`../coding-agent/deepseek-ai-deepseek-harness/apps/cli/src/process-shutdown.ts:1` 的有界关闭。

## Klaude 现在的真实行为

```text
Git 安装自动升级成功
  → 尝试 GET /api/server/status
  → server 忙碌：返回 pending，调用方不再重试
  → server 空闲：POST /api/server/reload (force=false)
      → uvicorn 退出并清理 session/runtime
      → server run 进程 execv 原启动命令
      → 客户端等待新 server 指纹匹配
```

- `src/klaude_code/cli/main.py:_maybe_start_auto_upgrade` 在交互式 TUI 启动时开启后台升级；`src/klaude_code/cli/uds_client.py:219` 的 `reload_server_after_upgrade` 只检查一次，遇到忙碌或 409 即返回 pending。后台路径的重载结果目前只记 debug 日志。
- `src/klaude_code/server/routes/server.py:34` 将 running、waiting_user_input、queued 视为 active；`:85` 的非强制 reload 遇到 active 返回 409。单纯「TUI 退出」不在这里触发 server reload。
- `src/klaude_code/server/server.py:194` 的关闭清理会中断运行中的 agent 并 flush 会话；`src/klaude_code/cli/server_cmd.py:53` 及 `:88` 在 reload 后用 `execv` 替换 server 进程。已有可用的原位重启机制，但缺少排空和待重启状态。
- `src/klaude_code/cli/uds_client.py:151` 的版本握手每个 CLI 进程只做一次，忙时警告后返回；之后空闲不会由同一个进程重试。下一个 CLI 进程如果在 server 空闲时连接，可能触发 reload。`src/klaude_code/tui/client/socket_client.py:700` 的 TUI 握手只报告兼容性问题，不接管 busy server 的重启。
- `src/klaude_code/update.py` 中的安装验证、Git 指纹和自动升级结果，与 server 的运行指纹是两种不同的状态。成功通知位于 `src/klaude_code/cli/main.py:_maybe_start_auto_upgrade` 和 `src/klaude_code/tui/runner.py:_show_upgrade_notice`；当前文案没有验证 server 是否已加载新版。

## 建议的下一步设计（未实施）

以 Klaude 已有的 `reload → execv → 指纹握手` 为底座，补 **server 拥有的待重启/排空状态**，而不是让后台升级线程长期轮询 `/status`。建议先定清楚以下合同：

1. **状态与请求**：更新器把目标指纹提交给 server，得到「已在运行 / 排空中 / 无法重启」的明确回应。server 将待重启状态保存在自己控制的生命周期中；重复请求幂等。考虑 server 进程在登记后崩溃时，谁负责重新核对目标版本。
2. **准入与排空**：接到请求后从所有入口停止接纳新 turn，包括 TUI、headless/API、排队 follow-up；同时允许已接受的任务输出最终事件、flush 会话。检查准入与 active-work 计数必须在同一边界协调，避免「刚看见空闲，就接进一个新任务」的竞态。
3. **等待输入与期限**：`waiting_user_input` 可能一直存在，queued work 也可能无限积累。需要产品决策：一直等待、超时后取消此次 reload，还是超时后中断并标记会话可恢复。默认不应暗中强制中断用户工作。
4. **切换与验证**：排空后复用现有 `execv`；由更新器或后续客户端以代码指纹而非 PID/命令返回值验证新 server。失败时报告「安装已更新，但 server 仍旧/未启动」，给出恢复命令。对 PyPI 安装也需取得目标运行指纹，不能只处理 Git checkout。
5. **TUI 与消息语义**：区分「新版本已安装，当前 CLI 需重启」「server 正在等待安全重启」「server 已验证运行新代码」。TUI 断开与重连、当前 CLI 仍运行旧模块，以及协议版本不兼容时的处理应分别验证。

建议先用一个跨 TUI + headless 的测试证明：忙碌时更新登记、禁止新 turn、原 turn 完成后 server 自动 reload、重连后新指纹一致；再覆盖等待输入、超时策略、重启失败和多个 CLI 同时更新。不要把 Codex 的超时强杀或 Hermes 的 gateway/supervisor 实现直接复制进 Klaude。
## 已实施：server 拥有升级与重启

实现位于 `src/klaude_code/server/upgrade.py` 的 `UpgradeCoordinator`，由 `server/app.py` 在 lifespan 中装配。

```text
klaude 启动（持久化状态显示有新版本）
  → POST /api/server/upgrade           登记，立即返回 pending / installing / ...
server 在每个空闲边界（turn 结束、队列清空、2s 轮询）检查：
  无 running / waiting_input / queued（含交互式 follow-up）
  → 关闭准入门（ws RunAgent/FollowUp、headless run/send 返回拒绝）
  → settle 后复核仍空闲
  → 线程内 perform_upgrade()：fetch、install、验证（复用原 Git/PyPI 逻辑）
  → 成功：request_reload → uvicorn 退出 → execv；失败：开门、phase=failed、通知已连接的 TUI
```

- **推迟安装**：安装只在空闲边界发生，忙碌 server 上 pending 一直保留，不会在有 turn 运行时替换 venv，避免新旧模块混载。
- **reload 也走同一条路**：`POST /api/server/reload {"when": "idle"}` 登记 `reload` 动作；已有 pending `upgrade` 时保留 upgrade。CLI 握手（`uds_client.verify_server_code`）对过期 server 只登记一次，不再轮询 `/status`。
- **入口**：TUI `/reload`、`klaude server reload --when-idle`、`klaude upgrade`（server 在线时改为让 server 安装并跟踪其状态，离线时才本地安装）。`klaude server status` 与 `GET /api/server/upgrade` 显示 phase / action / 等待中的会话。
- **消息语义**：TUI 启动通知描述 server 的登记结果；安装开始与失败会向所有已连接会话广播 NoticeEvent；重连后指纹变化时提示「server 已运行新代码，重启 klaude 以更新 CLI」。
- **未做**：TUI 进程自身不会自动重启（仍需用户重开）；`waiting_user_input` 不设超时，pending 一直等待，逃生口是 `klaude server reload --force`。
