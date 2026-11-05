# 子任务恢复回放

1. 已确认目标
   - 修复 fork-context 子任务结论重复。
   - 用 ai-gateway 长会话 `00a9f971130647da929b1e51bda0499e` 验证全部子任务及实际渲染。
   - 保留普通 `/fork-session` 完整历史及旧会话兼容。
2. 已观察原因
   - fork-context 继承的父会话正文和 TaskMetadataItem 被当作子任务历史回放。
   - 执行中的 peer_message 被当作 turn 边界，额外生成 TaskFinishEvent。
   - 上轮父子关系校验只修复重复加载子任务；Finder 从 8 次降至 1 次。
   - 三个 fork-context 子任务仍分别生成 17、22、23 次结束事件。
   - 安装环境指向当前源码；hc 的 t40 是用户恢复窗口。
3. 当前阶段
   - 已完成修复及独立正确性、可维护性审查；均无待修复发现。
   - 子会话从最后一条 fork 身份 reminder 开始回放；普通顶层分叉保留完整历史。
   - 身份 reminder 按稳定前缀识别，兼容缺少后来新增结尾的旧提示及角色提示。
   - 执行中的 peer、shell 和重试注入不再结束 turn；真实完成或中断后仍可唤醒。
   - 未找到可识别 reminder 的旧会话保留原行为；不修改原日志或模型上下文。
4. 验证记录
   - make format / make lint 通过。
   - make test：3686 passed、1 skipped、4 deselected；未运行网络测试。
   - session / TUI 专项：1660 passed、1 skipped。
   - 两条完整 fork 模型提示与改动前逐字相同。
   - 使用已安装 CLI 的 Python 完整渲染真实长会话全部 9 个子任务，核对结果正文及成功结论块。
   - compact、expanded、expanded refresh 和切回 compact 的结论数量均正确。
   - 同样验证完整历史的普通顶层分叉，以及模拟缺少 parent_session_id、保留旧 sub_agent_state 的格式。
   - 三个 fork-context 结果数：接入 Image 2.6 为 1、补齐 SVG 为 3、升级 Next.js 为 1。
   - SVG 的 3 次分别对应真实完成、KV 价格修复及后续进度回复；其他完成子任务各 1 次，取消的 Finder 无成功结论。
   - 验证脚本：/tmp/klaude-verify-sub-agent-replay.py；运行命令：/Users/dev/.local/share/uv/tools/klaude-code/bin/python -u /tmp/klaude-verify-sub-agent-replay.py。
   - 完整输出：/tmp/klaude-{real-session,ordinary-fork,legacy-session}-{compact,expanded,compact-toggle}.txt。
5. 相关路径
   - src/klaude_code/session/session.py
   - src/klaude_code/session/ledger.py
   - src/klaude_code/prompts/sub_agents.py
   - src/klaude_code/agent/runtime/sub_agent.py
   - tests/session/test_sub_agent_replay_order.py
   - tests/tui/test_shared_tasks.py
6. 下一步
   - 最后检查 hc 显示 t40 已结束；重新运行 klaude -r 加载本轮修改，无需重新安装。/refresh 只重放当前进程的事件 tape。
   - 按用户要求本地提交，不推送。