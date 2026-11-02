# OSC 7501 状态修复

## 已确认需求

1. 真实 feature detection 确认支持后，标题保留会话名称，移除手工状态前缀和动画；未知或不支持保持原行为。
2. 成功报告 done，致命失败报告 error，取消报告 idle；普通空闲、后台运行和历史重放不伪报完成。
3. blocked 使用结构化信息补 kind 和用户可读 msg，不按文案猜；错误 attention 不映射 blocked。
4. 保持现有架构；按用户要求将本次修复保存为一个 commit，不推送。

## 实际变更

- 在 prompt-toolkit 的现有输入解析中识别可变 OSC 7501 回复，支持 ST/BEL；首屏绘制后查询能力。
- 标题只在回复支持全部标准 states 后禁用状态前缀和动画；部分支持保留旧标题。
- 使用 SessionStatus.last_turn 和 turn ID 区分新结果；attach 快照只建立基线。
- 区分 attach 快照与运行中的 session_info 刷新；模型配置刷新不会清掉完成提示，第二次 attach 快照保留仍待处理的交互 payload。
- 本地合成的 session_info 状态只供显示，不作为新完成事件；实时结果沿服务端状态事件的原队列顺序处理。
- 运行中或 owned 后台任务仍活跃时不报告 done；完成结果保持到下一次工作或交互。
- 使用 attention 和交互请求结构区分 question / permission；当前协议无结构化 auth 请求，不推断 auth。
- msg 清除控制字符、压成单行、限制 UTF-8 2048 字节并编码为 base64；整条 record 去重。
- 原生状态模式下，提问框不再用旧动画参数重写标题，保留最新会话名称。

## 检查

- `make format`：通过。
- `make lint`：ruff、ty、import-linter 全部通过。
- `uv run pytest tests/tui tests/server/test_headless_unit.py -q --tb=short`：1590 passed，1 skipped。
- 回归覆盖：带空白 / 裸问号 / 扩展字段的 ST/BEL 回复、分段输入、普通键与 bracketed paste、TTY 忙重试、标题切换、三种 turn 结果、后台任务、消息长度、attach 双快照与实时元数据刷新。
- 独立审查：维护性无发现；正确性发现的提问框覆盖最新标题问题已修复，并补回归断言。
- 审查修复后重跑 `make format`、`make lint` 及上述回归：全部通过，1590 passed，1 skipped。
- 未验证：Rex 真终端人工测试（能力回复、标题与终端提示的实际显示）。

## 下一步

- 在 Rex 中重启 TUI，人工核对能力回复、无状态前缀标题、完成 / 失败提示及提问分类；代码、验证与独立审查已完成。
