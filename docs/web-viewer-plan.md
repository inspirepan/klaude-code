# klaude Web 会话查看器方案

> 状态：实施中（M1 前置清理已完成：export 已删除、debug 日志已常驻并轮转、
> payload 图片占位已落地）。本文是完整设计方案，决策已与作者逐项确认。
>
> **2026-08-29 修订**：
> ① 前端不再手写原生 ES modules，改为**直接 vendor deepseek-harness
> `packages/client/ui-trajectory`（及依赖的 ui-primitives、client-store）源码，
> 字节级不动**，Vite 构建、`@deepseek-ai/*` import 经 alias 接本地 shim，只重写数据
> 装配层；上游锚定 commit `cd5ef8148158`。覆盖决策 #1/#2/#3/#4/#7/#13/#25。
> ② 不做鉴权（决策 #19），只绑 localhost + Host 头校验。
> ③ 取消日志 tab，log viewer 与 `/debug` 命令删除，debug 日志只后台落盘（原 M6 删除）。
> ④ 账本 entry 映射按代码核实重写（见"账本：entry 映射"节），确认 rewind/checkpoint/
> UI-only entry 的展示口径。

## 背景

klaude 从"每命令独立进程的 TUI"改为常驻 server 架构后，server 已经具备
web 查看器所需的全部数据能力：

- WS attach 自动按需加载磁盘 session（`server/routes/ws.py:705-722` 的
  `InitAgentOperation` 路径），多客户端并发订阅互不影响，`peek=1` 只读模式现成。
- replay 机制完整：磁盘 `events.jsonl` 全量 + 内存事件磁带切片补齐进行中状态，
  实时磁带按 `event_seq` 去重无遗漏（`server/routes/ws.py:441-609`）。磁盘 history
  条目自身没有 `event_seq`，分页与定位使用 append-only 行索引，不能混用两种编号。
- 事件流实时：EventBus 广播后 5ms 微批次转发（`_BATCH_WINDOW_SECONDS = 0.005`），
  与 TUI 看到的是同一条流。
- 事件粒度足够重建轨迹：`user.message` / `assistant.text.*` / `thinking.*` /
  `tool.*` / `TaskStart/Finish`（sub-agent 级联转发），envelope 全带 `timestamp`。

现有两个 web 出口都是在进程分离时代设计的，与 server 架构不匹配：

- `tui/command/export_session_html.py`（静态导出）：快照式，数据只有落盘消息，
  无流式、无时间轴。**已删除**（含 assets、`/export` 命令注册与测试）。
- `app/log_viewer.py` + `log_viewer.html`（日志查看器）：HTTP 线程挂在 TUI 客户端
  进程上，TUI 退出即死。**不迁入 server，直接删除**（含 `/debug` 命令）；debug 日志
  只后台常驻落盘，不做任何展示 UI。

仓库根的 `web/` 目录是早期实验残留（仅 node_modules 与 tsbuildinfo），实施时一并清理。

## 目标

server 内嵌常驻 web 应用，`http://127.0.0.1:8765` 直接查看所有 klaude 会话的
实时轨迹。账本的语义对齐 deepseek：**列表本身就是模型的 append-only message
list**（SYSTEM/CONTEXT/USER/ASSISTANT/TOOL 行），左槽圆点是每次 LLM 请求的
元数据锚点。

**永久只读**：viewer 只看不操作（不回答交互、不中断、不发消息），协议固定走
`peek=1`。破坏面停留在"本机进程可查看历史"。

## 已确认决策清单

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 整体皮肤 | ~~布局照搬 deepseek，配色沿 log viewer 暖米系~~ **修订：完全沿用 deepseek 原皮（样式/CSS 变量不动），不做暖米系换肤** |
| 2 | 徽章配色 | **修订：随 vendor 源码原样，不再做 OKLCH 暖底调整** |
| 3 | 字体 | **修订：跟随 vendor UI 自带字体栈；Iosevka 内嵌决策作废，除非 vendor 样式实际需要** |
| 4 | 界面文案 | **修订：直接用 vendor `locales.ts` 的 zh 字典（t 函数由 shim 提供）；类型徽章保持英文原文** |
| 5 | 暗色主题 | 不做，只做浅色一套，CSS 变量集中预留 |
| 6 | 密度 | 13px 基准紧凑排版，行高约 20px，账本单行省略 |
| 7 | UI 规范 | **修订：UI 为 vendor 源码，不再套 better-* 准入与 interface-review；验收标准改为"与上游渲染一致"** |
| 8 | 操作面 | 永久只读（peek=1），不做任何会话操作 |
| 9 | 会话列表 | 平铺不分组，每行目录名 badge + 状态徽章，按最近活跃排序 |
| 10 | sub-agent | 嵌套分组内联（父 Task 行可展开，子事件按 task_id 归组缩进显示） |
| 11 | thinking | 不独立成行，并入 ASSISTANT 详情检查器 |
| 12 | 图片 | URL 图直接渲染；本地图加 `/api/file` 端点渲染（路径包含检查，根限 work_dir） |
| 13 | Markdown | **修订：用 vendor ui-primitives 的 `MarkdownText`（micromark + shiki + katex），micromark 默认不解析原始 HTML，安全姿势与 `html: false` 等价；账本行永远纯文本单行** |
| 14 | 检查器 | 照搬截图：Summary/Preview/Raw 三 tab + Request Timing 块；旧历史无持久 timing 时显示“未知” |
| 15 | 账本语义 | 单视图：append-only 全量显示，被 rewind/compaction 丢弃的行置灰+划线留在原位 |
| 16 | 请求圆点 | 覆盖全部 LLM 调用：主会话 step、compaction、/btw 侧问、sub-agent fork；新请求统一持久化请求记录，旧历史尽力重建 |
| 17 | 时间轴 | 全交互照搬：DOM/CSS 三泳道真实时间投影、拖拽框选聚焦、滚轮缩放、右键平移、hover tooltip |
| 18 | TCP 端口 | server 启动即绑 `127.0.0.1:8765`（占用顺延），`klaude web` 仅打开浏览器 |
| 19 | 鉴权 | **修订：不做鉴权**。只绑 `127.0.0.1`，无 token、无 cookie；仅保留 Host 头校验防 DNS rebinding |
| 20 | debug 日志 | 常驻 DEBUG 全量（已落地）；payload 内 base64 图片截断为占位（已落地）；轮转 50MB×10 + 目录总量 500MB（已落地） |
| 21 | export | 立即删除，不做导出按钮（已完成） |
| 22 | 搜索 | 客户端全文索引已加载行（无截断）+ 服务端搜索端点覆盖未加载历史，结果使用 history 行索引定位 |
| 23 | 长账本 | 服务端历史分页端点（尾部打开、顶部"加载更早"补页）+ 手写窗口化渲染（可视区+overscan，离散固定行高） |
| 24 | 列表实时性 | 列表页 5s 轮询；会话内轨迹走 WS 实时 |
| 25 | 前端组织 | **修订：vendor deepseek 源码 + Vite 构建（见下文"前端工程"），放弃无构建原生 ESM** |

## 页面结构

### 会话列表页 `/`

- 平铺列表，按最近活跃倒序。每行：会话标题、目录名 badge、状态徽章
  （running/waiting/idle）、更新时间、模型。
- 5s 轮询会话清单端点。
- 点击行进轨迹页；attach 未加载 session 由 server 按需初始化（现有机制）。

### 轨迹页 `/s/{session_id}`

三段布局：顶部工具栏（Duration/Turns/Calls 汇总 + 搜索）、泳道时间轴、事件账本。

#### 账本：entry 映射（2026-08-29 按代码核实并与作者确认）

转换路径：`events.jsonl` → `Session.get_llm_history()`（rebuild 处理 rewind/retract/
compaction，并把 `RewindEntry`/`ForkSummaryEntry`/`CompactionEntry` 物化成消息）→
provider adapter 入口 `attach_developer_messages` → provider 格式。请求 =
`{system 顶层参数, tools 参数, messages}`。

模型可见行（append-only payload 本体）：

| klaude entry | 账本行 | 模型侧实际去向 |
|---|---|---|
| system prompt + 工具目录 | SYSTEM（会话首行） | 顶层 `system`/`tools` 参数；不入盘，由 system-context 端点按当前配置重建（`SystemMessage` 类型是死代码，从不落盘） |
| `UserMessage` | USER | user 消息 |
| `AssistantMessage` | ASSISTANT | assistant 消息（thinking 并入详情） |
| `ToolCallPart`（在 `AssistantMessage.parts` 内）+ `ToolResultMessage` | TOOL（一行配对，call → result） | tool_use/tool_result 块；执行中的调用展示运行态 |
| `DeveloperMessage` | CONTEXT | `attach_developer_messages` 按 `attachment_position` 剥离拼进前一条 user/tool |
| `CompactionEntry` 的 summary | COMPACT 行 | `get_llm_history` 物化为首条 user(summary) |
| `RewindEntry` | REWIND 行（展示 note/rationale 通知文本） | `get_llm_history` 物化为 DeveloperMessage（`REWIND_REMINDER_TEMPLATE`） |
| `ForkSummaryEntry` | 仅在 fork 出的新 session 出现，为其 USER 首行 | 物化为 user(summary) |

DeveloperMessage 细分规则（已核实）：

- `parts` 文本全部进模型；`ui_extra` 是纯 UI 元数据（发送前剥离），不展示内容。
- 出现在第一条 user/tool 之前的 developer 无宿主可附着，会被 attach 丢弃，实际
  不进模型 → 不展示。
- checkpoint reminder（`<system-reminder>Checkpoint N</system-reminder>`）**不展示**，
  仅在状态扫描中用于 rewind 定位。

变换标记（`events.jsonl` 真 append-only，被丢弃内容仍在磁盘，必须可视）：

| klaude entry | 语义 | 账本渲染 |
|---|---|---|
| `RewindEntry` | 标记点与目标 checkpoint 之间的消息被丢弃 | REWIND 行（见上表）+ 被丢弃区间整段置灰划线 |
| `RetractEntry` | 撤回上一条 UserMessage | 不占行；被撤回的 USER 行置灰划线 |
| `CompactionEntry` | `[0:first_kept_index]` 被 summary 替换 | COMPACT 行 + 被压缩前缀置灰（可折叠为"已压缩 N 条"） |

账本必须以原始 JSONL 行为数据源，并用一遍状态扫描计算每行当前是否有效。
`rebuild_loaded_history()` 只用于模型输入和现有 replay；它会删除失效区间，不能作为账本数据源。
每行使用零基、append-only 的 `history_index` 作为稳定标识。prepend 更早页后，已有行标识不变。

不进 LLM 输入的 entry（`case _` 忽略，模型不可见）处置：

| klaude entry | 账本渲染 |
|---|---|
| `SideQuestionEntry` | BTW 行（问答面板样式可复用旧 export 的面板 CSS） |
| `SpawnSubAgentEntry` | sub-agent 嵌套分组起点（决策 #10 保留：读子 session 的 events.jsonl，子事件以 subtool 行内联缩进展示） |
| `InterruptEntry` / `StreamErrorItem` | 不占行；中断/错误状态进请求圆点 status（M4） |
| `CacheHitRateEntry` | 不占行，并入请求圆点 Usage |
| `TaskMetadataItem` / `TaskFileChangeSummaryEntry` | 不占行，进 turn 汇总（tokens/cost） |
| `FallbackModelConfigWarnEntry` | 不占行；降级信息进请求圆点 provider 字段（M4） |
| `PromptSuggestionEntry` / `AwaySummaryEntry` | 纯 UI 产物，**不展示**（与 TUI 不同：TUI 会把 AwaySummary 显示为 recap 面板） |
| session title | 不落盘（只写 meta.json），不存在展示问题 |

只展示落定消息：live 流式半截 assistant 状态不进账本（适配层 `partial` 恒为 null）；
执行中的工具调用除外（运行态 TOOL 行可展示）。

#### 请求圆点

- 每次 LLM 调用一个圆点，锚在左槽对应行旁：主会话 step 锚 ASSISTANT 行、
  compaction 锚 COMPACT 行、侧问锚 BTW 行、sub-agent 调用锚其分组内。
- 点击打开请求检查器，照搬 deepseek 布局：
  - Summary：Status（Completed/interrupted/error，由 `ResponseCompleteEvent` /
    `InterruptEntry` / `StreamErrorItem` 推导）、Provider、Model、Tool calls 数、
    Result 链接。
  - Options：模型配置 JSON（provider/model/effort/maxTokens 等）。
  - Usage：Input（Cached/Other）、Output（Reasoning/Content）、成本。
    数据源 `UsageEvent.usage` + `CacheHitRateEvent` / `ForkCacheHitRateEvent`。
    展示遵守 AGENTS.md 的 inclusive 语义（net = total − cached − cache_write 等）。
  - Timing：Started（`StepStartEvent` 时间戳）、Total duration、
    TTFT（推导值：首个 `thinking.start`/`text.start` − `step.start`）、
    Generation、Throughput（output_tokens ÷ 生成时长）。

请求身份与持久化规则：

- live 主会话与 sub-agent 请求优先按 `response_id` 聚合；`StepStartEvent` 没有
  `response_id`，按同 session/task 中紧随其后的 response 关联。旧 history 中
  `AssistantMessage.response_id` 可能为空，此时使用 session 内 step 顺序生成仅供展示的稳定键。
- 新增模型不可见的 `LLMRequestEntry`，统一记录所有新 LLM 调用，而不是从当前
  session 配置猜测历史请求。字段至少包含：`request_id`、`kind`（step/compaction/
  side_question/sub_agent/fork）、锚点（`response_id`、`history_index` 或关联 entry id）、
  provider/model/options、status、usage、started/first_token/completed 时间戳和 tool call 数；
  options 使用现有安全 dump 规则，禁止持久化 API key、云凭证和授权头。
  history codec 将它当作 sidecar entry；`convert_history_to_input` 必须忽略它。
- compaction、`/btw` 和 fork 当前没有完整持久化 Usage/Timing，实施 M4 时由各调用点
  写入同一种 `LLMRequestEntry`。`SideQuestionEntry` 另补可选 `request_id`，用于与请求记录关联。
- 旧会话没有 `LLMRequestEntry`：主 step 可从 `AssistantMessage` 尽力重建 Usage 和结果；
  compaction、`/btw`、fork 只显示现有字段。无法恢复的 Options、TTFT、Generation 和
  Throughput 显示“未知”，不得显示 0 或套用当前模型配置。

#### 记录检查器（点账本行）

照搬截图：Summary（来源/状态/tokens 分解含 cache 与成本）+ Preview
（markdown-it 渲染）+ Raw（原始 entry JSON）三 tab；ASSISTANT 行附 Thinking
区块与 Request Timing。

完整 SYSTEM 文本与工具 schema 不放进会重复刷新的 `session_info` 帧。检查器首次打开
SYSTEM 行时，通过按需只读端点获取一次，并在客户端缓存。

#### 泳道时间轴

- 三泳道：Input（user 消息时刻）、Model（step 区间，区分 TTFT 段与生成段）、
  Tools（tool.start→result 区间）。live 数据来自 envelope 时间戳；历史数据优先来自
  `LLMRequestEntry`，旧历史缺失的区间只画时刻标记或标为 timing unavailable。
- 交互照搬 deepseek：拖拽框选区间聚焦账本、滚轮缩放时间域、右键平移、
  hover 出精确时刻 tooltip。参考实现实际使用绝对定位 DOM + CSS 变量，不是 canvas；
  本项目沿用该方式，复用其缩放锚点、框选、边缘自动平移数学。
- 跟随语义：初始与流式更新停留尾部；向上滚动暂停跟随。

### 日志 tab（已取消）

~~log viewer 迁入 server~~ **2026-08-29 修订：不做日志展示 UI**。debug 日志常驻
后台落盘（已实施）即全部诉求；`app/log_viewer.py`、`log_viewer.html` 与 `/debug`
命令在实施时一并删除，原 log viewer 占用的 8765 端口由 web 应用接管。

## 数据通道与协议改动

复用为主，新增为辅：

1. **复用 WS** `/api/sessions/{id}/ws?replay=1&peek=1`：replay + live，零改动。
   浏览器是同构客户端，TUI 看到的 web 都看到。
2. **新增 TCP 监听**：FastAPI 双绑定（UDS 给 CLI/TUI 不变，`127.0.0.1:8765` 给
   浏览器），静态目录伺服 + 下列 REST 端点挂在同一 app。
3. **新增 REST 端点**：
   - `GET /api/web/sessions`：会话清单（磁盘全量 + 活跃状态 + 目录/模型/更新时间），
     数据来自 `SessionLiveIndex` + `session_registry` + headless 队列。
   - `GET /api/web/sessions/{id}/history?before_index=N&limit=M`：原始历史分页。
     `before_index` 是零基 JSONL 行索引且为 exclusive；省略时返回尾页。响应中的每项带
     `history_index`，并返回 `next_before_index` 与 `has_more`。
   - `GET /api/web/sessions/{id}/search?q=...`：服务端搜索 `events.jsonl`，
     返回匹配 entry 的 `history_index` 列表，前端跳转定位并按需加载所在页。
   - `GET /api/web/file?path=...`：本地图片渲染，`resolve()` 后做路径包含检查，
     根限该 session 的 work_dir 与 session 图片目录。
   - `GET /api/web/sessions/{id}/system-context`：按需返回该 session 当前恢复出的完整
     system prompt、工具目录与 schema；仅供 SYSTEM 检查器使用，不随状态帧重复广播。
4. **历史与事件 schema 补充**：
   - `AssistantTextEndEvent` 增加 `stop_reason` 字段（live 时检查器可见，
     持久化本来就有）。
   - attach 时的 `session_info` 只补当前模型的轻量摘要（provider/model/effort/
     maxTokens）和 SYSTEM 端点可用状态，不携带完整 prompt/schema。
   - 新增上述 `LLMRequestEntry` 及 live 对应事件，持久化每次调用的配置、Usage、状态和
     timing；新字段均可选，保证旧 history 可解码。
5. **TTFT 策略**：live 可由事件时间戳推导；新请求同时写入 `LLMRequestEntry` 供重启后
   查看。现有 replay 会把同一 AssistantMessage 合成的事件赋成同一 `created_at`，因此
   旧会话不得据此计算 TTFT/Generation。

## 常驻 debug 日志（已完成）

- server 启动即开 DEBUG 级别文件日志（`server/server.py` 的 `start_server` 调用
  `set_debug_logging(True, write_to_file=True)`），不再依赖 `/debug` 或 `--debug`
  开关；`/api/server/debug` 端点保留为关闭开关。
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
  的 sanitizer 对同名键任意深度脱敏（防御纵深）；日志目录 0700、文件 0600。
- OpenRouter 的 `echo_upstream_body` 调试选项改为环境变量
  `KLAUDE_OPENROUTER_DEBUG_ECHO` 显式开启（否则常驻 debug 会让每个生产响应
  都带上回显的请求体）。
- 文件 formatter 对无 `debug_type_label` 的外源记录（`logging.getLogger(__name__)`）
  使用 `defaults={"debug_type_label": "GENERAL"}`，不再整条丢弃。

## 安全

- 只绑 `127.0.0.1`，无鉴权；校验 Host 头（仅允许 `localhost`/`127.0.0.1`）防浏览器
  DNS rebinding 跨域读取。
- 全部端点只读；`/api/web/file` 做 `resolve()` 后路径包含检查。
- Markdown 渲染由 vendor `MarkdownText`（micromark）承担，不解析原始 HTML；所有进入
  DOM 的模型/工具内容走转义或 `textContent`。

## 前端工程（2026-08-29 修订）

- **路线**：vendor deepseek-harness 源码（commit `cd5ef8148158`，MIT，附 LICENSE 与
  来源说明），**vendored 文件字节级不动**；`@deepseek-ai/*` import 由 Vite alias +
  tsconfig paths 接到本地 shim，平台差异全部收敛在 shim 层和我们自己的数据适配层。
- **目录**：源码在仓库根 `web/`（取代原残留目录），`vite build` 输出到
  `src/klaude_code/server/web/` 静态目录随 wheel 打包。
  - `web/vendor/dsh-client-ui-trajectory/`：ui-trajectory `src/client/` 的 UI 层
    （TrajectoryView/Toolbar/Timeline/Table 等组件、CSS modules、layout/timeline/
    record/contract/virtual-rows/search-index/preview/locales/copy-codes/
    duration-store）。**不复制**平台胶水：`index.ts`、`invariant.ts`、6 个
    `trajectory-*-definition.ts` 与 `trajectory-snapshot-builder.ts`（cordis DI +
    ui-conversation 流水线，由我们的数据适配层替代）。
  - `web/vendor/dsh-client-ui-primitives/`：整体复制（JsonTree/MarkdownText/Tooltip/
    图标/hooks，零 cordis 耦合；第三方依赖 shiki/katex/micromark/clsx/anser 经 npm）。
  - `web/vendor/dsh-client-store/`：`contract.ts` + `index.ts`（zustand+immer 快照
    store 引擎，424 行）。
  - `web/src/shim/`：手写薄 shim——`ui-slots`（InjectFace/PropsLocale/PropsRenderSlots/
    TranslateNS 类型）、`dsh-client-ui-conversation/client`（ConversationNode/
    RequestView/ToolCallBlock 等**纯类型**，尽量从上游原样摘抄）、`dsh-attachment`、
    `dsh-client-locale/client`。t() 直接用 vendor locales.ts 的 zh 字典实现。
  - `web/src/app/`：我们的应用层——entry、hash 路由（`/` 列表页、`/s/{id}` 轨迹页）、
    klaude WS/REST 客户端、**数据适配器**（klaude events.jsonl entry + live 事件 →
    `TrajectorySnapshot`：eventNodes/eventLocations/requests/callSchemas/partial/
    runningCalls）。selector hook 用 `useSyncExternalStoreWithSelector` 在 store 上合成。
- **构建**：`web/package.json`（pnpm），`pnpm typecheck`（tsc --noEmit）与
  `pnpm build`（vite build）必须绿；React 18 + TypeScript，`allowImportingTsExtensions`
  兼容 vendor 的 `.ts` 后缀 import。
- **CI/打包**：wheel 只收 `src/klaude_code/server/web/` 产物；`web/node_modules` 与
  构建中间产物不进 git。

## 里程碑

1. **M1 地基**：预绑定 UDS 与 TCP socket，并由同一个
   `uvicorn.Server.serve(sockets=[...])` 承载（lifespan 只运行一次）；TCP 从 8765
   占用顺延，实际端口通过 UDS `/api/server/status` 暴露给 `klaude web`。随后完成
   Host 头校验中间件、静态伺服、会话清单端点和列表页。清理：根 `web/` 残留目录
   （由前端源码目录取代）、`app/log_viewer.py` + `log_viewer.html` + `/debug` 命令
   （含测试）。（export 删除已完成。）
2. **M2 账本**：历史分页端点 + WS attach + 数据适配层（klaude entry →
   `TrajectorySnapshot`：entry 映射、置灰语义、sub-agent 嵌套 subtool）+ 记录检查器
   数据源接通。
3. **M3 时间轴**：时间轴数据接通（live envelope 时间戳 + `LLMRequestEntry` 区间），
   对旧历史的 timing 缺失做明确降级。
4. **M4 请求圆点**：先落地统一 `LLMRequestEntry` 与各调用点持久化，再完成圆点锚定、
   请求检查器（Summary/Options/Usage/Timing）和事件 schema 补充（stop_reason、轻量
   session_info、按需 system-context）。
5. **M5 搜索**：客户端全文索引 + 服务端搜索端点 + 跳转定位。

（日志 tab 已取消；日志常驻、轮转、图片占位已提前完成。）

每个里程碑完成后跑 `make lint` / `make test`；前端验收标准为"与上游 vendor 渲染
一致"。
