# klaude Web 会话查看器方案

> 状态：实施中。已落地：M0-1 删 checkpoint（`7c3723f6`）、M0-2 坐标统一 + 行号 + `scan_history`
> （`e2350d67`）、M1 双 socket / Host guard / 静态伺服 / `klaude web` / 删 log viewer（`f2950f92`）、
> M2-B 磁盘历史分页 API + `HistoryAppendedEvent`（`7e93dc34`）、M2-F1 适配器 + 轨迹页（`17bbc715`）、
> M2-B2 行上 turn/step/auto（`d57073b4`）、M2-F2 列表页 + WS 在线状态（`e9b89759`）、
> M3 泳道 D1（`e0714f61`）、M4-B `LLMRequestEntry`/`stop_reason`/system-context（`c4d670b7`）、
> M4-F 请求检查器 + SYSTEM 行 + Schema（`880677c6`）、M5-B 服务端搜索（`e896609b`）、
> M5-F 客户端搜索跳转到未加载历史（`37f7b38a`）。**M0–M5 全部落地**；遗留项见 `web/VENDOR.md` 的 open items。本文是完整设计方案，决策已与作者逐项确认。
> 交互细节见配套文档 [web-viewer-ux-spec.md](web-viewer-ux-spec.md)。
>
> **2026-08-29 修订**：① 前端改为复用 deepseek-harness `ui-trajectory` 源码；② 不做鉴权；
> ③ 取消日志 tab；④ 账本 entry 映射按代码核实重写。
>
> **2026-08-30 修订（本版）**：
> ⑤ 前端路线由"字节级 vendor + shim"改为 **fork**（复制进仓库、自由修改、不跟上游同步）。
> 上游锚点 `cd5ef8148158c3a752a658978873241fdf8e2bbc`（origin/master，2026-08-28）已确认；
> 本地克隆 `~/code/coding-agent/deepseek-harness` 工作树落后，需 `git merge --ff-only origin/master`。
> ⑥ 泳道条尺度模型**刻意偏离** deepseek：固定每条最小宽度 + 原生横向滚动（决策 #17）。
> ⑦ sub-agent 不做 subtool 嵌套；子会话在会话列表中作为独立会话展示（决策 #10）。
> ⑧ 数据模型订正：`rebuild_loaded_history` 只做结构裁剪，物化在 `get_llm_history`；
> `first_kept_index` 是内存列表坐标而非文件行号；旧历史主 step 的 timing **已持久化**；
> replay 不读 `events.jsonl`。
> ⑨ 新增 **M0**：删除 checkpoint 机制、修复 compaction 坐标 bug、新标记带文件行坐标、
> loader 与账本共用一遍扫描。
> ⑩ 冷会话（未加载进 server）只走 REST 从磁盘读，不初始化 agent；WS 只用于在线会话。
> ⑪ 会话清单复用 `GET /api/headless/sessions`；`LLMRequestEntry` 范围缩至 compaction / `/btw` / fork。

## 背景

klaude 从"每命令独立进程的 TUI"改为常驻 server 架构后，server 已经具备
web 查看器所需的全部数据能力：

- WS attach 自动按需加载磁盘 session（`server/routes/ws.py:705-724` 的
  `InitAgentOperation` 路径；另有 `_ensure_session_agent`（`ws.py:264-286`）在每个 op 帧前
  兜底），多客户端并发订阅互不影响，`peek=1` 只读模式现成（`ws.py:728` `can_input = not peek_mode`）。
- replay 机制完整但**不读磁盘**：`_send_attach_replay`（`ws.py:441-493`）从内存
  `conversation_history` 经 `get_history_item(limit=base_len)` 合成 `replay_history` 帧
  （裸事件 dict，带 `timestamp`，无 `event_seq`），有 tape 时只到 `base_history_len`；之后
  tape 切片 + live 由 `_forward_events`（`ws.py:496-608`）按 `event_seq` 去重。同一
  `AssistantMessage` 合成的所有事件共享一个 `timestamp`（`session/session.py:678-800`）。
- 事件流实时：EventBus 广播后 5ms 微批次转发（`_BATCH_WINDOW_SECONDS = 0.005`，
  `_BATCH_MAX_SIZE = 50`）；批量帧是 **JSON 数组**，单事件是对象（`ws.py:575-590`）。
- 事件粒度足够重建轨迹：`user.message` / `assistant.text.start|delta|end` /
  `thinking.*` / `tool.call` / `tool.call.start` / `tool.result` / `tool.output.delta` /
  `task.start` / `task.finish`（sub-agent 级联转发），envelope 全带 `timestamp`
  （`protocol/events.py:108-118`）。

viewer 的账本以磁盘 `events.jsonl` 为数据源（见"数据通道"），WS 只承担在线会话的
进行中状态，因此 replay 的上述限制不影响账本。

现有两个 web 出口都是在进程分离时代设计的，与 server 架构不匹配：

- `tui/command/export_session_html.py`（静态导出）：**已删除**（`57307b0d7`）。
- `app/log_viewer.py` + `log_viewer.html`（日志查看器）：HTTP 线程挂在 TUI 客户端
  进程上，默认端口 `8765`（`log_viewer.py:14`），TUI 退出即死。**不迁入 server，直接删除**
  （含 `/debug` 命令 `tui/command/debug_cmd.py`）；debug 日志只后台常驻落盘。

仓库根没有 `web/` 目录（`c1d33bac9` 已删）；`.gitignore` 里 `node_modules/`、
`*.tsbuildinfo`、`web/.vite` 等是残留条目，`web/` 本身未被 ignore。

## 目标

server 内嵌常驻 web 应用，`http://127.0.0.1:8765` 直接查看所有 klaude 会话的
实时轨迹。账本的语义对齐 deepseek：**列表本身就是模型的 append-only message
list**（SYSTEM/CONTEXT/USER/ASSISTANT/TOOL 行），左槽圆点是每次 LLM 请求的
元数据锚点。

**永久只读**：viewer 只看不操作（不回答交互、不中断、不发消息），协议固定走
`peek=1`。破坏面停留在"本机进程可查看历史"。

**体验一致性**：UI 代码 fork 自 deepseek，验收标准是"与上游一致，偏离项仅限
[web-viewer-ux-spec.md](web-viewer-ux-spec.md) 的'klaude 刻意偏离'一节"。

## 已确认决策清单

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 整体皮肤 | 沿用 deepseek 原皮：fork `ui-theme/src/styles/{base,design-platform,scrollbar,shiki}.css`，不换肤 |
| 2 | 徽章配色 | 随 fork 源码 |
| 3 | 字体 | `ui-theme/base.css` 系统字体栈，无 webfont；唯一字体资源是 KaTeX 随 `katex.min.css` 引入 |
| 4 | 界面文案 | 用上游 `locales.ts` 的 `zh` 字典（174 键，与 `en` 1:1）+ 12 个 common 键（`copy.*`/`json.*`/`markdown.footnotes`）；**类型徽章保持英文**：在 fork 字典里把 `kind.*` 8 个键改回英文 |
| 5 | 暗色主题 | 不做；`design-platform.css` 删掉两个 `body[data-ds-dark-theme]` 块（约 150 行） |
| 6 | 密度 | 随上游：账本行 12px/18px 字号、30px 行高、折叠摘要行 20px；检查器 13px/20px |
| 7 | UI 规范 | fork 源码，不套 better-*/interface-review；验收 = 与上游渲染一致 + 偏离清单 |
| 8 | 操作面 | 永久只读（peek=1） |
| 9 | 会话列表 | **修订**：复用 `GET /api/headless/sessions?include_children=1&include_archived=1&limit=500`（`routes/headless.py:376`，`_serialize_row` 已含 title/work_dir/model/updated_at/state/activity/pending/parent_session_id/archived；不带两个 flag 时子会话与已归档会话被隐藏，`limit` 只计根会话）；状态词表六值 `queued \| running \| waiting_input \| idle \| completed \| failed`（冷会话是 `completed`，`idle` 指有 TUI 挂着且在等输入）；平铺按最近活跃倒序，子会话折叠在父行下 |
| 10 | sub-agent | **修订**：不做嵌套、删除 `subtool` kind。子会话作为独立会话行出现在列表（带 parent badge，可按父折叠）；父轨迹中 Agent 工具的 TOOL 行，其检查器提供"打开子会话轨迹"链接 |
| 11 | thinking | 不独立成行，并入 ASSISTANT 详情检查器 |
| 12 | 图片 | 上游已删除内联 `<img>`，图片走 `renderImages` 渲染槽（未注册则不显示）；我们实现该槽：URL 图直连，本地图经 `/api/web/file`（三个根，见安全） |
| 13 | Markdown | 上游 `ui-primitives` `MarkdownText`（micromark + shiki + katex）；无 `allowDangerousHtml`，raw HTML 保留为文本（`render.tsx:273-275`）；唯一 `dangerouslySetInnerHTML` 只吃 shiki 产物 |
| 14 | 检查器 | 随上游 tab 集：记录 `Summary/Preview/Raw/(Source)`；tool `Summary/(Payload)/(Result)/Schema/Timing`；compacted `Summary/Raw Output`；system `(Diff)/System Prompt/Tools`；请求 `Summary/Options/Usage/Timing`。旧历史主 step 的 TTFT/吞吐/时长来自 `AssistantMessage.usage`，**不显示"未知"**；只有 compaction / `/btw` / fork 的旧记录缺 timing |
| 15 | 账本语义 | 单视图：append-only 全量显示，被 retract/compaction（及旧会话 rewind）丢弃的行置灰+划线留在原位；状态由 server 一遍扫描给出（见"账本状态计算"） |
| 16 | 请求圆点 | 覆盖全部 LLM 调用。主会话 step 直接用持久化的 `AssistantMessage.usage`；compaction / `/btw` / fork 新增 `LLMRequestEntry` 持久化；旧记录尽力重建 |
| 17 | 时间轴 | **修订（刻意偏离）**：固定每条最小宽度 + 原生横向滚动，尾部跟随；保留 deepseek 全部手势（滚轮缩放改 px/记录、右键拖动、左键框选、hover tooltip、双击/Esc 清除）。上游是"全域塞进容器 + 缩放/平移窗口"，记录越多每条越窄 |
| 18 | TCP 端口 | server 启动即绑 `127.0.0.1:8765`（占用顺延），`klaude web` 仅打开浏览器；**先删 log viewer 再占端口** |
| 19 | 鉴权 | 不做。只绑 `127.0.0.1`，保留 Host 头校验防 DNS rebinding |
| 20 | debug 日志 | 常驻 DEBUG 全量；payload 图片占位；轮转 50MB×10 + 目录总量 500MB（均已落地） |
| 21 | export | 已删除，不做导出按钮 |
| 22 | 搜索 | **修订**：上游是实时过滤（空格分词 AND，3s 索引节流），不是高亮跳转；沿用。服务端搜索端点仍做，用于未加载页，返回 `line_index` |
| 23 | 长账本 | **修订**：随上游用 `@tanstack/react-virtual`（>100 行启用，固定行高估算，`anchorTo: 'end'`），不手写窗口化；服务端历史分页（尾部打开 + 顶部补页） |
| 24 | 列表实时性 | 列表页 5s 轮询；会话内在线状态走 WS |
| 25 | 前端组织 | **修订**：fork（见"前端工程"），Vite 构建 |
| 26 | checkpoint 机制 | **新增**：删除（M0）。含 RewindTool、每回合 checkpoint DeveloperMessage、`RewindEntry` 写入、system prompt 相关文案、`meta.next_checkpoint_id`；`/rewind` 与 fork 只按 UserMessage 索引选 pivot；保留 `RewindEntry` 解码与 rebuild 兼容以读旧文件 |
| 27 | 历史坐标 | **新增**：账本行标识用零基文件行号，命名 `line_index`（`history_index` 已被 `fork_session_cmd.py:69`/`copy_cmd.py:83` 用作内存列表索引）；新写入的 `CompactionEntry`/`RetractEntry` 附带行坐标；loader 不再按 compaction 切列表（见 M0） |
| 28 | 冷会话 | **新增**：未加载会话只走 REST 从磁盘读，不触发 `InitAgentOperation`；在线会话才开 WS |

## 页面结构

### 会话列表页 `/`

- 数据源 `GET /api/headless/sessions?include_children=1&include_archived=1&limit=500`。每行：
  会话标题、目录名 badge、状态徽章（六值，见决策 #9；running/waiting_input 视觉上标为在线）、
  更新时间、模型；已归档行压暗。客户端按标题/目录/模型过滤。
- 子会话（`parent_session_id` 非空）显示 parent badge，默认折叠在父行下。
- 5s 轮询。点击行进轨迹页。

### 轨迹页 `/s/{session_id}`

三段布局（与上游一致）：顶部工具栏 32px（时长/轮次/调用三个开关 + 搜索）、
泳道时间轴 50px、事件账本（表格 + 右侧推挤式检查器）。

#### 账本：entry 映射（2026-08-30 按代码核实并订正）

转换路径（以代码为准）：

1. `events.jsonl` → `JsonlSessionStore.load_history`（`store.py:273`，按 mtime/size 缓存；
   未知 `type` 行**静默丢弃**，`codec.py:43-45` + `store.py:310-312`）。
2. `Session.load` → `rebuild_loaded_history`（`session/history.py:79`）：**只做结构裁剪**——
   应用 `RetractEntry`（删最近匹配的 UserMessage）、旧会话 `RewindEntry`（截断到 checkpoint
   标记）；M0 之前还按最后一个 `CompactionEntry.first_kept_index` 切前缀并把它归一为 1
   （`history.py:99-102`），M0 后不再切（见下）。**它不物化任何消息。**
3. `Session.get_llm_history`（`session.py:483`）：`_convert` 把 `RewindEntry` 物化为
   `DeveloperMessage(REWIND_REMINDER_TEMPLATE)`、`ForkSummaryEntry` 物化为
   `UserMessage(FORK_SUMMARY_USER_PREFIX + summary)`；最后一个 `CompactionEntry` 的
   summary 前置为 `UserMessage`，其余 `CompactionEntry` 过滤掉；
   `_strip_dangling_tool_calls`（`session.py:451-481`）为无结果的 tool call **合成**
   `ToolResultMessage(status="error", TOOL_INTERRUPTED_MESSAGE)`——磁盘上不存在这些行。
4. agent 层按 `isinstance(item, message.Message)` 过滤 sidecar entry
   （`agent/step.py:279-285` 等调用点）；provider adapter 的 `case _` 是不可达的兜底。
5. `attach_developer_messages`（`llm/input_common.py:285-318`）剥离 `DeveloperMessage`，
   按 `attachment_position` 拼进前一条 user/tool；第一条 user/tool 之前的 developer 丢弃；
   `ui_extra` 不进模型。请求 = `{system 顶层参数, tools 参数, messages}`。

模型可见行（append-only payload 本体）：

| klaude entry | 账本行（上游 kind） | 模型侧实际去向 |
|---|---|---|
| system prompt + 工具目录 | SYSTEM（`system`，会话首行） | 顶层 `system`/`tools` 参数；不入盘，由 system-context 端点按当前配置重建（`SystemMessage` 类型是死代码，从不落盘） |
| `UserMessage` | USER（`user`） | user 消息。**非人类 UserMessage 要标注**：`source="bash_mode"`（按字段）、空响应续跑提示（`task.py:963` 常量文本）、流错误续跑提示（`step.py:236`）、sub-agent fork-context reminder（`sub_agent.py:256-259`）——后三种按已知文本识别，标 `auto` 标签 |
| `AssistantMessage` | ASSISTANT（`message`） | assistant 消息（thinking 并入详情） |
| `ToolCallPart` + `ToolResultMessage` | TOOL（`tool`，一行配对 call → result） | tool_use/tool_result 块；执行中的调用展示运行态；**无结果且非运行中**的调用标 "interrupted"（模型侧收到的是合成 error 结果） |
| `DeveloperMessage` | CONTEXT（`context`） | 按 `attachment_position` 拼进前一条 user/tool |
| `CompactionEntry` 的 summary | COMPACT 行（`compacted`） | 物化为首条 user(summary) |
| `RewindEntry`（仅旧会话） | REWIND 行（新增 kind） | 物化为 DeveloperMessage；M0 后不再产生 |
| `ForkSummaryEntry` | 仅在 fork 出的新 session 出现，为其 USER 首行 | 物化为 user(summary)。注意 fork 会把整个 kept 前缀**深拷贝**进新 session（`agent_ops.py:1242-1257`），新账本行全部有新 `line_index` |

DeveloperMessage 细分规则（已核实）：

- `parts` 文本全部进模型；`ui_extra` 是纯 UI 元数据，不展示内容。
- 出现在第一条 user/tool 之前的 developer 会被 attach 丢弃 → 不展示。
- checkpoint reminder（`<system-reminder>Checkpoint N</system-reminder>`）是普通 developer
  消息，**会进模型**（拼到前一条 user）。M0 删除后新会话不再产生；旧会话中**不展示**。

变换标记（`events.jsonl` 真 append-only：`store.py:155-159` 只以 `"a"` 模式追加，
任何路径都不重写/截断文件；被丢弃内容仍在磁盘，必须可视）：

| klaude entry | 语义 | 账本渲染 |
|---|---|---|
| `RetractEntry` | 撤回最近一条文本完全匹配 `retracted_text` 的 UserMessage（`history.py:55-76`）；不匹配则不动 | 不占行；被撤回的 USER 行置灰划线（`data-discarded`） |
| `CompactionEntry` | 活跃列表 `[0:first_kept_index]` 被 summary 替换。`first_kept_index` 是**压缩当时内存列表**的索引（`compaction.py:239,330`），不是文件行号 | COMPACT 行 + 被压缩前缀置灰（可折叠为"已压缩 N 条"） |
| `RewindEntry`（旧会话） | 标记点与目标 checkpoint 之间的消息被丢弃；checkpoint ID 在 rewind 后**复用**（`session.py:420`），原始文件可有重复 `Checkpoint N` | REWIND 行 + 被丢弃区间置灰划线 |

#### 账本状态计算（server 端一遍扫描）

账本以原始 JSONL 行为数据源，每行用零基 `line_index` 作稳定标识（prepend 更早页后不变）。
**前端不重放任何 rebuild 逻辑**；行状态由 server 计算并随分页响应下发：

```
status ∈ {active, retracted, compacted, rewound, unknown, sidecar}
dropped_by: line_index | null      # 导致该行失效的标记行
```

算法（`session/history.py` 新增 `scan_history(raw_lines) -> ScanResult`，
`rebuild_loaded_history` 改为其薄封装，loader 与账本共用一份实现）：

1. 逐行解码；解码失败或未知 `type` 的行记 `unknown`，**仍占行号**。
2. 维护 `active: list[(line_index, item)]`。
3. 遇 `RetractEntry`：优先用 `retracted_line`（B，新写入才有）；否则回退为从尾部找最近
   UserMessage 且 `join_text_parts == retracted_text`。命中则标 `retracted(by=r)` 并从 active 移除。
4. 遇 `CompactionEntry`：优先用 `first_kept_line`（B）；否则 `active_lines[:first_kept_index]`。
   前缀中尚未失效的行标 `compacted(by=c)`。**compaction 只是状态标记，不从 `active` 删除任何
   项**——M0 之后 loader 不再切列表，`active` 始终等于"原始行 − retract/legacy rewind"，
   `first_kept_index` 就是相对这份未切列表的坐标（与 live 会话一致）。
5. 遇旧会话 `RewindEntry`：在**当前 active** 中找 `Checkpoint {id}` 的 DeveloperMessage
   （逐步重放即可消歧复用的 ID），其后的行标 `rewound(by=w)`。
6. 非 Message 的 sidecar entry 标 `sidecar`（不占账本行，但供检查器/圆点消费）。

结果按 `(mtime_ns, size)` 缓存并可增量延伸（新 append 只会新增标记，不会改变已扫过行的
状态，除了被新标记覆盖的那些）。

`rebuild_loaded_history()` 的输出只用于模型输入和 TUI replay；它删除失效区间，不能作为账本数据源。

不进 LLM 输入的 entry（模型不可见）处置：

| klaude entry | 账本渲染 |
|---|---|
| `SideQuestionEntry` | BTW 行（新增 kind；问答面板样式） |
| `SpawnSubAgentEntry` | 不占行；为对应 Agent 工具 TOOL 行提供"打开子会话"链接（`session_id` 字段即子会话 id，子会话有独立 `events.jsonl`） |
| `InterruptEntry` / `StreamErrorItem` | 不占行；中断/错误状态进请求圆点 status |
| `CacheHitRateEntry` | 不占行，并入请求圆点 Usage |
| `TaskMetadataItem` / `TaskFileChangeSummaryEntry` | 不占行，进 turn 汇总（tokens/cost） |
| `FallbackModelConfigWarnEntry` | 不占行；降级信息进请求圆点 provider 字段 |
| `PromptSuggestionEntry` / `AwaySummaryEntry` | 纯 UI 产物，**不展示**（TUI 把 AwaySummary 显示为单行 `※ recap:`，`tui/components/away_summary.py`） |
| `LLMRequestEntry`（新增） | 不占行；请求圆点数据源（compaction / `/btw` / fork） |
| session title | 不落盘（只写 meta.json），不存在展示问题 |

只展示落定消息：live 流式半截 assistant 状态走上游 `partial`（不进 `eventNodes`）；
执行中的工具调用走 `runningCalls`。

#### 请求圆点

- 每次 LLM 调用一个圆点，锚在左槽对应行旁：主会话 step 锚 ASSISTANT 行、
  compaction 锚 COMPACT 行、侧问锚 BTW 行；sub-agent 的请求在子会话自己的轨迹页。
- 上游请求身份是 `assistant\0turn\0step` / `compaction\0seq`（`TrajectoryTable.tsx:530-534`），
  不再从分组标题字串合成编号，未知请求**不画圆点**；klaude 适配层必须为每个请求提供
  `requestNumbers`。
- 点击打开请求检查器：
  - Summary：Status（Completed/interrupted/error，由 `AssistantMessage.stop_reason` /
    `InterruptEntry` / `StreamErrorItem` 推导）、Provider、Model、Tool calls 数、Result 链接。
  - Options：模型配置 JSON（provider/model/effort/maxTokens 等）。
  - Usage：Input（Cached/Other）、Output（Reasoning/Content）、成本。
    数据源 `AssistantMessage.usage`（`protocol/models/usage.py`：input/cached/cache_write/
    reasoning/output tokens、四项成本、`cache_hit_rate`）+ `CacheHitRateEntry`。
    展示遵守 AGENTS.md 的 inclusive 语义："`Usage` 用 inclusive counts，消费方要减法得净值"；
    `input_tokens` 是总 prompt 且包含 `cached_tokens + cache_write_tokens`；Anthropic-Bedrock
    例外，跨 provider 取真实总量用 `max(input_tokens, cached_tokens + cache_write_tokens)`。
  - Timing：Started（`usage.created_at` = 请求开始，`llm/usage.py:55`）、Completed
    （`AssistantMessage.created_at`）、TTFT（`usage.first_token_latency_ms`）、Total
    （`usage.task_duration_s`）、Throughput（`usage.throughput_tps`）。**这些字段已持久化**
    （真实磁盘数据核实），旧会话主 step 无需降级。

请求身份与持久化规则：

- live 主会话请求按 `response_id` 聚合；`StepStartEvent` 没有 `response_id`，按同 session 中
  紧随其后的 response 关联。旧 history 中 `AssistantMessage.response_id` 可能为空，此时用
  session 内 step 顺序生成仅供展示的稳定键。
- 新增模型不可见的 `LLMRequestEntry`，**只**记录 compaction / `/btw` / fork 三类调用
  （主 step 的 `AssistantMessage.usage` 已足够）。字段：`request_id`、`kind`
  （compaction/side_question/fork）、锚点（关联 entry 的 `line_index` 或 `response_id`）、
  provider/model/options、status、usage、started/first_token/completed 时间戳和 tool call 数；
  options 使用现有安全 dump 规则，禁止持久化 API key、云凭证和授权头。
  加入 `HistoryEvent` union（`protocol/message.py:364-380`）即自动注册 codec；不加进
  `agent/step.py:279` 的 `message_types` 元组即不会进模型，adapter 零改动。
- 这三处**已经算出 usage 但丢弃了**：`agent/side_question.py:100-114`（`SideQuestionResult.usage`）、
  `agent/compaction/compaction.py:324`（`CompactionResult.usage`）、`agent/rewind/summary.py`。
  M4 是接管道，不是加测量。`SideQuestionEntry` 另补可选 `request_id`。
- 旧会话没有 `LLMRequestEntry`：compaction / `/btw` / fork 只显示现有字段（summary、
  `cache_hit_rate`、`tokens_before`），Options/TTFT/Throughput 显示"未知"，不得显示 0 或
  套用当前模型配置。

#### 记录检查器（点账本行）

随上游：右侧推挤式面板（`clamp(320px, 38%, 440px)`，可拖 320–720px，双击复位），
tab 集见决策 #14。ASSISTANT 行附 Thinking 区块与 Request Timing。

完整 SYSTEM 文本与工具 schema 不放进会重复刷新的状态帧。检查器首次打开 SYSTEM 行时，
通过按需只读端点获取一次，并在客户端缓存。

#### 泳道时间轴

- 三泳道（上游 lane 0/1/2，标签 Input/Model/Tools）：Input（user/context/system 时刻）、
  Model（step 区间，TTFT 段与生成段用渐变区分）、Tools（tool.call → result 区间）。
- 数据源：在线会话用 envelope 时间戳；历史用持久化字段——step 区间
  `[usage.created_at, AssistantMessage.created_at]`，TTFT 用 `usage.first_token_latency_ms`；
  tool 区间 `[AssistantMessage.created_at, ToolResultMessage.created_at]`（call 起点近似为
  assistant 完成时刻）。缺字段的区间只画 2px 时刻标记。
- **尺度模型（刻意偏离，决策 #17）**：`trackWidth = max(容器宽, N × pxPerRecord)`，
  `overflow-x: auto`，位于尾部时新记录到来自动跟随。滚轮缩放改 `pxPerRecord`（光标锚点换算
  `scrollLeft`），右键拖动改 `scrollLeft`，左键框选聚焦账本，hover 出 tooltip，双击/Esc 清除。
  上游的 `sequence`/`duration` 两种域模式与空闲压缩算法保留。
- 跟随语义：初始与流式更新停留尾部；向上滚动暂停跟随（账本 2px 阈值，随上游）。

### 日志 tab（已取消）

不做日志展示 UI。debug 日志常驻后台落盘（已实施）即全部诉求；`app/log_viewer.py`、
`log_viewer.html` 与 `/debug` 命令在 M1 一并删除，原 log viewer 占用的 8765 端口由 web 应用接管。

## 数据通道与协议改动

账本数据走 REST（磁盘、带状态），进行中状态走 WS（仅在线会话）。这与上游快照模型一致：
`eventNodes`（落定行）+ `partial`（流式 assistant）+ `runningCalls`（执行中工具）。

1. **新增 TCP 监听**：FastAPI 双绑定（UDS 给 CLI/TUI 不变，`127.0.0.1:8765` 给浏览器），
   静态目录伺服 + 下列 REST 端点挂在同一 app。现状是 `uvicorn.Config(uds=...)` +
   `serve()`（`server/server.py:153-177`）；目标是预绑定两个 socket 交给同一个
   `uvicorn.Server.serve(sockets=[...])`（uvicorn 0.41 下 lifespan 只跑一次）。注意传 `sockets=`
   时 uvicorn 跳过整个 uds 分支，socket 权限与 unlink 顺序（`server.py:136,184`）由我们负责。
   `/api/server/status`（`routes/server.py:51-69`）新增 `web_port` 字段。
2. **会话 meta** `GET /api/web/sessions/{id}/meta` →
   `{session_id, title, work_dir, model, parent_session_id, created_at, updated_at, state, loaded, line_count}`；
   `loaded` = `session_registry.has_session_actor`，前端据此决定是否开 WS。
   **历史分页（磁盘）** `GET /api/web/sessions/{id}/history?before_line=N&limit=M`
   或 `?after_line=N&limit=M`（互斥；都省略返回尾页；`limit` 默认 500、静默夹到 1–2000）：
   直接读 `events.jsonl`，不初始化 agent；`ScanResult` 按 `(mtime_ns, size)` 缓存，冷读首页
   约 300ms（6k 行），热页个位数 ms。每项
   `{line_index, status, dropped_by, entry, turn_index, step_index, auto}`——`entry` 与磁盘行
   逐字节一致（`{"type","data"}`，解不出的行为 `null` + `status: "unknown"`）；`turn_index` 是
   **人类回合**的 1 基绝对序号（首个人类 user 之前为 0）、`step_index` 是 AssistantMessage 在回合
   内的 1 基序号、`auto` 只在 UserMessage 行上，标记 bash_mode / 空响应续跑 / 流错误续跑 /
   sub-agent fork-context 四类非人类输入（判定常量在 Python 侧，前端不重复实现）。顶层另返回
   `line_count`、`turn_count`、`has_more`（`before_line` 模式指 `rows[0]` 之前还有行；
   `after_line` 模式指 `rows[-1]` 之后还有行）、`next_before_line`（= `rows[0].line_index`，
   `after_line` 模式为 null）。翻页以 `has_more` 为准。
3. **在线会话 WS** `/api/sessions/{id}/ws?replay=1&peek=1`：仅当 `session_registry.has_session_actor`
   为真才连接。viewer 忽略 `replay_history` 帧里已落盘的内容（以 REST 为准），只消费
   live 事件构造 `partial`/`runningCalls`。落盘完成由新增 `HistoryAppendedEvent`
   （挂在 `store.py:159` 的 `_on_history_written` 钩子，携带 `line_count`）通知，viewer 收到后
   拉 `after_line` 增量并用落定行替换进行中状态。客户端必须处理：批量帧为 JSON 数组；
   非 envelope 帧 `connection_info` / `session_info` / `usage.snapshot` / `replay_history` /
   `replay_complete` / `follow_ups_dequeued` / `error`；`event_seq` 在 server 重启后从 1 重计，
   attach 合成 envelope 的 `event_seq=0`；`connection_info.code_fingerprint` 浏览器算不出，
   忽略即可（否则永久假阳性）。
4. **会话清单**：复用 `GET /api/headless/sessions?include_children=1&include_archived=1&limit=500`
   （两个 flag 已存在；见决策 #9）。
5. **搜索** `GET /api/web/sessions/{id}/search?q=...`：服务端搜索 `events.jsonl`，
   返回匹配 entry 的 `line_index` 列表，前端跳转定位并按需加载所在页。
6. **本地文件** `GET /api/web/file?session_id=...&path=...`：本地图片渲染，`resolve()` 后做
   路径包含检查（根见"安全"）；只放行位图（png/jpg/gif/webp），SVG 可执行脚本 → 415；越界 403、
   超 25MB 413、不存在 404；响应带 `X-Content-Type-Options: nosniff`。
7. **系统上下文** `GET /api/web/sessions/{id}/system-context`：按需返回该 session 当前恢复出的
   完整 system prompt、工具目录与 schema；仅供 SYSTEM 检查器使用。
8. **历史与事件 schema 补充**：
   - `AssistantTextEndEvent` 增加 `stop_reason`（`protocol/events.py:446` 现只有
     `session_id/timestamp/response_id`）。
   - `session_info` 只补当前模型的轻量摘要（provider/model/effort/maxTokens）和 SYSTEM
     端点可用状态。
   - 新增 `LLMRequestEntry`（见请求圆点）、`HistoryAppendedEvent`、`SideQuestionEntry.request_id`。
   - `CompactionEntry.first_kept_line`、`RetractEntry.retracted_line`（可选字段，见 M0）。
   新字段均可选，旧 history 可解码（`protocol/` 无 `extra="forbid"`，pydantic 默认忽略未知字段）。

## M0：历史层整洁化（viewer 之前的独立 PR）

目的：让 `events.jsonl` → 真实对话历史的映射只有一套坐标、一份实现，账本与 loader 共用。

1. **删除 checkpoint 机制**（决策 #26）。牵连：`tool/rewind_tool.py`、`agent/rewind/manager.py`
   的 checkpoint 分支、`agent/task.py` 的 `create_checkpoint`（`:655`）与 pending rewind
   （`:898-913`）、`session/session.py` 的 checkpoint API（`:360-423`）、`tui/command/rewind_cmd.py`
   的 "model-rewind pivot" 分支（`:193-203`；用户 pivot 已按文本匹配）、`tui/components/tools/_rewind.py`、
   `agent/system_prompt.py` 两处文案、`prompts/messages.py` 的 `CHECKPOINT_TEMPLATE`、
   `session/meta.py` 的 `next_checkpoint_id`、`protocol/op.py`/`events.py` 的 rewind op/event。
   保留：`RewindEntry` 类型与 `_apply_rewind_entry_to_history`（读旧文件）。
2. **修复 compaction 坐标 bug（已实测复现）**：reload → 再次 compaction → 再 reload 会把已
   压缩的消息复活进 LLM 视图。根因：loader 把内存列表切成 `[C_last(first_kept_index=1), kept...]`，
   之后 live compaction 记下的 `first_kept_index` 相对这份切过的列表；下次 reload 对未切列表
   套用该索引即错位。修法：`rebuild_loaded_history` **不再按 compaction 切**，内存列表始终是
   "原始行 − retract/rewind"（与 live 会话完全一致，live 本来就不切）；`get_llm_history` 已在请求
   时按最后一个 compaction 切，不受影响；TUI replay 若要维持"reload 后只看压缩后内容"，在
   `get_history_item` 加显示层裁剪。补测试 `tests/session/test_session_load_active_history.py`：
   reload → compact → reload。
3. **新标记带文件行坐标**：`Session` 维护与 `conversation_history` 平行的 `_history_lines: list[int]`
   （load 时来自扫描，append 时按行计数递增，retract 时同步删除）。`CompactionEntry` 新增
   `first_kept_line`，`RetractEntry` 新增 `retracted_line`（均可选）。写入点：
   `agent/task.py:491,572`（`compaction.to_entry()` 前查 `_history_lines[cut_index]`）、
   `session.py:425-449`（retract）。
4. **共享扫描**：`session/history.py` 新增 `scan_history`（见"账本状态计算"），
   `rebuild_loaded_history` 改为薄封装；`load_history` 增加返回行号的变体，未知 type 行占位不丢。
5. 命名：REST 与内部一律 `line_index`，避免与既有 `history_index`（内存列表索引）混淆。

## 常驻 debug 日志（已完成）

- server 启动即开 DEBUG 级别文件日志（`server/server.py:166` 调用
  `set_debug_logging(True, write_to_file=True)`），不再依赖 `/debug` 或 `--debug`
  开关；`POST /api/server/debug` 端点保留为关闭开关。
- 轮转 50MB×10（`DEBUG_LOG_MAX_BYTES`/`DEBUG_LOG_BACKUP_COUNT`，独立于
  server.log 的 10MB×3）；启动时清理：保留 3 天、目录总量 500MB 硬上限。
  轮转不 gzip：压缩在 `emit()` 里同步执行会卡住 server 事件循环。
- `log_debug` 的 LLM_PAYLOAD 统一走 `log.py` 的 `debug_json` 消毒（7 个 provider
  client 调用点已从裸 `json.dumps` 切换）：base64 图片截断为占位（保留
  `data:image/...;base64` 前缀与 `truncated,len=N` 标记）。覆盖三种形状：
  Anthropic `media_type` 兄弟键、Google `mime_type` / OpenAI `mimeType` 兄弟键、
  `data:` URL 字符串。原文路径在 payload 层不可得，占位只保留 mime 与字节数。
- 密钥保护（常驻前提）：`agent/runtime/llm.py` 的 4 处 LLM_CONFIG dump 排除
  `api_key`/`aws_access_key`/`aws_secret_key`/`aws_session_token`；`debug_json`
  的 sanitizer 对同名键（含 `authorization`/`x-api-key`）任意深度脱敏；日志目录 0700、文件 0600。
- OpenRouter 的 `echo_upstream_body` 调试选项改为环境变量
  `KLAUDE_OPENROUTER_DEBUG_ECHO` 显式开启。
- 文件 formatter 对无 `debug_type_label` 的外源记录使用
  `defaults={"debug_type_label": "GENERAL"}`，不再整条丢弃。

## 安全

- 只绑 `127.0.0.1`，无鉴权；校验 Host 头（仅允许 `localhost`/`127.0.0.1`）防浏览器
  DNS rebinding 跨域读取。仓库目前没有任何 StaticFiles/CORS/TrustedHost 中间件，
  只有 `_EnvSyncMiddleware`（`server/app.py:30-56`）。
- 全部端点只读；`/api/web/file` 做 `resolve()` 后路径包含检查，允许三个根：
  该 session 的 `work_dir`、session 图片目录
  `~/.klaude/projects/<key>/sessions/<id>/images/`（`const.py:292-294`，用户附图与 Read/LookAt
  产物都落这里、内容寻址）、以及 `ImageURLPart.source_file_path` / 未 frozen 的
  `ImageFilePart.file_path` 可能指向的系统 temp 目录（`tui/input/images.py:65`）。
- Markdown 渲染由 fork 的 `MarkdownText` 承担，不解析原始 HTML；所有进入 DOM 的模型/工具
  内容走转义或 `textContent`。
- `server/**` 不在 ruff TID251 的 allowlist 里，且 server 启动 `os.chdir(home_dir)`：新路由模块
  的所有路径必须经 `klaude_code.workspace.resolve_workspace_path` + 显式 `work_dir`。

## 前端工程（2026-08-30 fork 路线）

**来源**：deepseek-harness `cd5ef8148158c3a752a658978873241fdf8e2bbc`，MIT
（`Copyright (c) 2026 DeepSeek`，各包 `license: "MIT"`）。fork 目录附 `LICENSE.deepseek-harness`
与 `VENDOR.md`（记上游 commit、复制范围、偏离清单）。**不跟上游同步。**

**目录**：源码在仓库根 `web/`，`vite build` 输出到 `src/klaude_code/server/web/`
随 wheel 打包（uv_build 默认收全部数据文件，无需配置；但要加 `wheel-exclude` 防
`node_modules/` 误入——现有 wheel 已因 `skill/assets` 达 1.6 万文件）。

复制范围（约 9.1k 行 UI 代码 + 2.3k 行 CSS）：

- `web/src/trajectory/`：`ui-trajectory/src/client/` 的 UI 集合——`TrajectoryTable.tsx`
  （3204 行）+ `.module.css`（1770）、`layout.ts`（1133）、`TrajectoryTimeline.tsx`（739）
  + `.module.css`、`TrajectoryView.tsx`、`TrajectoryToolbar.tsx` + `.module.css`、`timeline.ts`、
  `trajectory-record.ts`、`trajectory-search-index.ts`、`trajectory-virtual-rows.ts`、
  `trajectory-preview.ts`、`trajectory-contract.ts`（只留 `TrajectorySnapshot`/
  `TrajectoryRequestHeaderState`）、`locales.ts`、`copy-codes.ts`、`views.module.css`、
  `src/css-modules.d.ts`（在包根，不在 `src/client/`）。
  **删除**：cordis/流水线胶水 `index.ts`、`invariant.ts`、`trajectory-snapshot-builder.ts`、
  `trajectory-definition-common.ts`、6 个 `trajectory-*-definition*.ts`、
  `trajectory-event-projection.ts`、`duration-store.ts`；死文件 `TrajectoryCell*`、
  `TrajectoryTurn*`、`TrajectoryTurnHeader*`、`TrajectoryGroupHeader*`。
  上游测试 `tests/{table,views,layout,virtual-rows}.client.spec.*` 可随迁作为回归基线。
- `web/src/ui-primitives/`：`ui-primitives/src/` 整体（除 `invariant.ts`，唯一 cordis 耦合）。
  ui-trajectory 只用其中 `JsonTree`/`MarkdownText`/`Tooltip`/`extractMarkdownPlainText`
  与 5 个图标；`TerminalBlock`/`Toast`/`Modal` 等可删以去掉 `anser` 依赖。
  唯一全局 CSS 副作用：`MarkdownText.tsx:23` `import 'katex/dist/katex.min.css'`。
- `web/src/theme/`：`ui-theme/src/styles/{base,design-platform,scrollbar,shiki}.css`；
  `design-platform.css` 删两个 dark 块。ui-trajectory + ui-primitives 共消费 123 个自定义属性，
  其中 90 个由 ui-theme 定义、33 个在各自 module.css 内定义；`--dsh-composer-height` 由上游
  composer 宿主注入，我们没有 composer，直接把 `views.module.css:27` 的回退改为 0。
- `web/src/contract/`：复制 `ui-conversation/src/client/contract/{records,request-inspection,
  context-provenance}.ts`（约 460 行），加本地扁平类型 `ContentBlock`、`ToolSchema`、
  `ImageAttachmentRef`，手写扁平的 `ConversationLocation`
  （`{kind:'session'|'unresolved'} | {kind:'turn';turn:{turn}} | {kind:'step';turn:{turn};step:{step}}`）
  替代上游依赖 `SessionEvent` 的深版本；`ConversationNode` 只保留 klaude 会产生的 arm
  （user/steering/assistant/context/compaction/tool-result；`layout.ts` 也只处理这些）。

Day-1 改动（import 重写清单，不含功能偏离）：

- `@deepseek-ai/dsh-client-ui-conversation/client` → `../contract`：`trajectory-contract.ts:1-5`、
  `trajectory-record.ts:5`、`layout.ts:5-14`、`TrajectoryTable.tsx:18-20`、`TrajectoryView.tsx:4-6`。
- `@deepseek-ai/dsh-attachment` → 本地 `ImageAttachmentRef`：`trajectory-record.ts:4`、
  `layout.ts:15`、`TrajectoryTable.tsx:17`。
- `@deepseek-ai/dsh-client-ui-primitives` → `../ui-primitives`：`TrajectoryTable.tsx:6-15`、
  `TrajectoryTimeline.tsx:7`、`TrajectoryToolbar.tsx:4`、`trajectory-preview.ts:3`。
- `@deepseek-ai/dsh-client-ui-slots` → 本地 `TranslateNS`（`(key, params?) => string`）：
  `TrajectoryToolbar.tsx:3`、`locales.ts:196`、`trajectory-contract.ts:6`；
  `TrajectoryView.tsx:7` 的 `InjectFace/PropsLocale/PropsRenderSlots` 换成显式 `TrajectoryViewProps`。
- `@deepseek-ai/dsh-client-store` → 删：`TrajectoryView.tsx:8` 的 `SnapshotStore<boolean>` 换成
  `actualDuration: boolean` + setter（`localStorage` 记忆）。
- 删三处 `declare module`：`trajectory-contract.ts:75-96`、`locales.ts:187-193`。
- `TrajectoryView.tsx:120-152`：`useSession/useTrajectory/useDuration/renderSlot` 等注入 hook
  换成 props（`snapshot`、`session:{openState,loadingOlder,hasMore}`、`actualDuration`、
  `renderImages`、`t`、`loadOlder`）。

我们自己写的：

- `web/src/app/`：entry、hash 路由（`/` 列表页、`/s/{id}` 轨迹页）、REST/WS 客户端、
  **数据适配器**（REST 行 + 状态 + live 事件 → `TrajectorySnapshot`：`eventNodes`/
  `eventLocations`/`requests`/`callSchemas`/`partial`/`runningCalls`，另加 `requestNumbers`
  与 `discarded` 标记）。适配器取代上游 1752 行 Definition 机制，只需产出快照字段。
- `web/src/locale.ts`：174 个 trajectory 键（`kind.*` 改英文）+ 12 个 common 键。
- 偏离改动（见 UX 规格"klaude 刻意偏离"）：泳道尺度模型；删 `subtool`（kept 集 18 处，
  多为 `kind === 'tool' || kind === 'subtool'` 折叠）；新增 `rewind`/`btw` kind（编译期穷举点
  4 处：`TrajectoryTable.tsx:42` `KIND_LABEL_KEY`、`:113` `KIND_ICON`、
  `TrajectoryTimeline.tsx:86` `timelineKindLabel`、`timeline.ts:51` `laneFor`；字典 2 处）；
  行级 `data-discarded`（`<tr>` 已有 14 个 `data-*` 状态属性，`stateOf()` `TrajectoryTable.tsx:713`
  集中派生，加一处 + 一条 CSS，样式可镜像 `data-timeline-focus="outside"` 的压暗）。

**依赖**（版本来自上游 manifest）：`react`/`react-dom ^18.2.0`、`@tanstack/react-virtual ^3.14.9`、
`diff ^9.0.0`、`clsx ^2.0.0`、`shiki ^4.3.1`、`@shikijs/langs ^4.3.1`、`katex ^0.16.47`、
`mdast-util-{from-markdown ^2.0.3, gfm ^3.1.0, math ^3.0.0}`、`@types/mdast ^4.0.4`、
`micromark-{core-commonmark ^2.0.3, extension-gfm ^3.0.0, extension-math ^3.1.0, factory-space ^2.0.1,
util-character ^2.1.1, util-classify-character ^2.0.1, util-sanitize-uri ^2.0.1, util-symbol ^2.0.1,
util-types ^2.0.2}`；构建 `vite ^6`、`@vitejs/plugin-react ^4`、`typescript ^6.0.3`。
不需要 zustand/immer/use-sync-external-store（随 duration-store 一起删）。

**tsconfig**（必须保留，否则上游代码要改写）：`allowImportingTsExtensions` +
`rewriteRelativeImportExtensions`（所有相对 import 带 `.ts/.tsx` 后缀）、
`exactOptionalPropertyTypes`、`noUncheckedIndexedAccess`、`moduleResolution: "bundler"`、
`jsx: "react-jsx"`。`pnpm typecheck` 与 `pnpm build` 必须绿。

## 里程碑

0. **M0 历史层整洁化**（独立 PR）：删 checkpoint 机制；loader 不再按 compaction 切并补
   reload→compact→reload 测试；`_history_lines` + `first_kept_line`/`retracted_line`；
   `scan_history` 共享扫描；`line_index` 命名。跑全量 `make test`。
1. **M1 地基**：预绑定 UDS 与 TCP socket，同一 `uvicorn.Server.serve(sockets=[...])` 承载；
   `/api/server/status` 加 `web_port`；Host 头校验中间件；静态伺服；列表页接
   `/api/headless/sessions`。清理：`app/log_viewer.py` + `log_viewer.html` + `/debug` 命令
   （含测试）——**先删再占 8765**。
2. **M2 账本**：fork 导入 + Vite 构建绿；`contract/` 与适配器；历史分页端点（磁盘 + 状态）；
   `HistoryAppendedEvent`；在线会话 WS 接 `partial`/`runningCalls`；置灰语义；`rewind`/`btw` kind；
   删 `subtool`；sub-agent 链接。
3. **M3 时间轴**：数据接通（live envelope + 持久化 usage 字段）；泳道尺度偏离实现；
   旧 compaction/btw/fork 缺 timing 的降级。
4. **M4 请求圆点**：`LLMRequestEntry`（compaction / `/btw` / fork 三个调用点接管道）、
   `SideQuestionEntry.request_id`、圆点锚定与 `requestNumbers`、请求检查器、`stop_reason`、
   轻量 `session_info`、按需 system-context。
5. **M5 搜索**：客户端实时过滤（随上游）+ 服务端搜索端点 + 跳转定位。

每个里程碑完成后跑 `make lint` / `make test`；前端验收标准为"与上游一致 + 偏离清单"。
