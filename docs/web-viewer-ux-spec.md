# klaude Web 查看器交互规格

> 配套 [web-viewer-plan.md](web-viewer-plan.md)。本文是 deepseek-harness `ui-trajectory`
> 轨迹页在上游 commit `cd5ef8148158c3a752a658978873241fdf8e2bbc`（2026-08-28）的**行为规格**，
> 按源码逐项核实（路径相对 `packages/client/ui-trajectory/src/client/`，行号为该 commit）。
> 用途：① fork 后的验收基线——改了什么、没改什么，一目了然；② 最后一节列出 klaude
> 的刻意偏离，偏离之外的一切以本文为准。

页面组合（`TrajectoryView.tsx:446-505`）：纵向 flex——工具栏 32px（sticky）→ 时间轴 50px
（固定）→ 账本（`flex:1; min-height:0; overflow:hidden`）。账本内部是横向 flex：可滚动表格
面板 + 可选的右侧检查器 `<aside>`。

## 1. 泳道时间轴

### 1.1 尺度模型（上游）

track 是 `position: relative; overflow: hidden`（`TrajectoryTimeline.module.css:53-58`），
外层 grid `44px minmax(0,1fr)`、高 50px、`overflow: hidden`（`:14-20`）。**没有 `overflow-x`、
没有 `scrollLeft`、没有 `min-width`。** 模型是"把整个时间域塞进容器宽度"：

- 所有 span 按**全域百分比**定位在内层绝对定位层 `.lanes`（`:118-125`）里；
- 缩放/平移只改 React state `viewport = [domainStart, domainStart + domainDuration]`，
  两个 CSS 变量随之重算：

```
--trajectory-domain-left  = -(domainStart - model.start) / domainDuration * 100%
--trajectory-domain-width =  fullDuration / domainDuration * 100%          (TrajectoryTimeline.tsx:333-345)
--trajectory-span-left    = (span.start - model.start) / fullDuration * 100%
--trajectory-span-width   = (span.end - span.start)   / fullDuration * 100%  (:676-678, 713-725)
```

合成后的像素数学（W = track 宽）：`pxPerUnit = W / domainDuration`，
`x(t) = (t - domainStart) * pxPerUnit`。放大时内层比容器宽，用负 `left` 平移，容器不滚动。
**平移 = 改 `domainStart`，不是 `scrollLeft`**。后果：未缩放时记录越多每条越窄（最小 2px）。

### 1.2 时间域（`timeline.ts`）

`deriveTrajectoryTimeline(turns, mode)`（`timeline.ts:70-113`）→ `{start, end, spans[], turnBoundaries[]} | null`
（null 显示 "No timing data"）。四种模式由两个布尔选出（`TrajectoryView.tsx:284-286`）：

| actualDuration | actualTime | mode | 域单位 | span |
|---|---|---|---|---|
| false | false | `sequence`（默认） | 记录序号 | `[i, i+1]` 等宽 |
| true | false | `duration` | 毫秒，**去掉空闲间隙** | `[start−idle, end−idle]` |
| false | true | `time`（控件隐藏） | 原始毫秒 | 零宽时刻 |
| true | true | `actual`（控件隐藏） | 原始毫秒 | `[start, end]` |

`actualTime` 开关带 `hidden`（`TrajectoryToolbar.tsx:79`），只做 `sequence`/`duration` 即可。

**空闲压缩**（`timeline.ts:115-180`）：按 `(start, end)` 排序，维护并集 `coveredUntil`；
`span.start > coveredUntil` 的空洞累加到 `removedIdle`，每个 span 记下此时的前缀和；
`projected = span - removedIdleBySpan[span]`。只删真正空闲的墙钟时间，并发工具调用保持重叠。
测试：起点 1000/4000/40000、各 1s → `duration` 模式映射为 1000-2000/2000-3000/3000-4000。
无 `startedAt` 的记录在计时模式下**丢弃**（`:56-62`）；运行中（`timeSeconds === null`）
时长为 0 → 2px 起点标记，不画伸长的 live 条。

### 1.3 DOM

```
section.root                      ← wheel 监听（含标签槽）
  div.plot                        ← grid 44px | 1fr，50px
    div.labels                    ← Input/Model/Tools 三行标签（top 7/21/35px）
    div.track[tabindex=0]         ← 全部指针事件；overflow hidden
      button.earlierHistory       （条件）
      div.hoverLine               （条件）
      div.selection + div.selectionEdges   （条件；视口分数坐标）
      div.turnBoundaries[--trajectory-domain-*]  ← 投影层
      div.lanes[--trajectory-domain-*]           ← 投影层
        Tooltip > span.span[data-timeline-span=kind][data-timeline-record-index=N]
```

两套坐标并存：**域投影**（lanes、turn 边界）与**视口分数**（选区、hover 线，用
`visibleRange.start*100%`，`:620-641`）。

### 1.4 泳道与 span

- 3 条泳道，间距 14px，条高 8px：`top: calc(var(--trajectory-span-lane) * 14px); height: 8px`
  （css `:153-170`）；`.lanes` 上下各内缩 7px。
- 泳道分配（`timeline.ts:46-52`）：`tool|subtool → 2`（Tools），`message|compacted → 1`（Model），
  `system|user|context → 0`（Input）。compaction 走 Model 道、SYSTEM 走 Input 道，都是普通 span。
- 间隙 `--trajectory-span-gap: min(width% × 0.08, 1px)`（`:715`）：8% 比例间隙，1px 饱和。
- 最小宽 `width: max(2px, calc(var(--width) - gap - gap)); min-width: 2px`；`time` 模式
  `data-equal-duration` → 固定 8px。
- **同道重叠不做布局**，直接叠放；hover/current 的 span `z-index:1` + 1px 底色环 + 2px 强调环。
- ASSISTANT 的 TTFT 分段：`timingRecorded && start ≤ firstToken ≤ completed` 时
  `--trajectory-assistant-ttft = ttft/(ttft+decoding)*100%` 驱动一个硬边 `linear-gradient`
  （TTFT 段颜色向背景混 54%，之后是生成色）——单元素，不是两个元素（css `:200-208`）。
- 裁剪：只渲染与域窗口相交的 span，外加 `selectedIndex` 那条（`:671-674`）。

### 1.5 滚轮缩放

`root` 上 `{passive:false}` + `preventDefault()`（`:348-379`）：

```
anchorFraction = clamp01((clientX - trackRect.left) / trackRect.width)
nextDuration   = clamp(domainDuration * exp(deltaY * 0.0015), min(MIN_ZOOM, full), full)
                 MIN_ZOOM = 4 条记录（sequence）| 20ms（计时模式）
if nextDuration >= full * 0.999 → viewport = null（回到全域）
anchorTime = domainStart + anchorFraction * domainDuration
nextStart  = clamp(anchorTime - anchorFraction * nextDuration, model.start, model.end - nextDuration)
```

缩放前 `setAnimateViewport(false)`，缩放不做过渡。

### 1.6 平移与框选（同一 track，按键分流）

`pointerdown`（`:424-455`）捕获指针：

- **右键**：平移手势 `{anchorClientX, anchorStart, pannable: viewport !== null}`，
  `data-panning` → `cursor: grabbing`；`contextmenu` 被阻止（`:599-601`）。
  移动：`nextStart = clamp(anchorStart − (Δx / W) * domainDuration, …)`。
  抬起：位移 < `MINIMUM_DRAG_PX (3)` → **右键单击清除选区**，缩放不动。
- **左键**：框选。锚点时间 = `domainStart + fraction * domainDuration`，`draft` 实时渲染。
  缩放状态下拖到边缘自动平移（`:478-507`）：边缘区 `min(32px, max(1, W*0.08))`，
  强度 `clamp01(edgeDistance/edgeWidth)`，每次 pointermove 步进 `domainDuration * 0.025 * max(0.2, strength)`。
  抬起（`:522-561`）：位移 < 3px 且落在 span 上 → 清选区 + `onRecordSelect(index)`（选中 + 打开检查器 + 滚动）；
  否则提交；短于 `min(domainDuration, full / spans.length)` 的选区替换为**居中最小宽选区**，
  点空白也能聚焦约 1 条记录；单击额外 `onRecordFocus(最近 span)`。
- 双击 track → 清除选区；track 有焦点时 `Escape` → 清除；`pointercancel` → 丢弃 draft/pan/hover。

### 1.7 选区渲染

两个 `pointer-events:none` 覆盖层，视口分数定位（`:620-641`）：

- `.selection`：12% 品牌色（拖动中 18%）；**外侧压暗用两个巨型 box-shadow**，不加元素：
  `box-shadow: -100vw 0 0 100vw <bg-layer-1 58%>, 100vw 0 0 100vw <bg-layer-1 58%>`。
- `.selectionEdges`：`::before/::after` 3px 把手（拖动中 2px）。

span 按与 `draft ?? range` 的闭区间相交得到 `data-selected`；`false` → `opacity: .2`。
搜索不匹配 → `opacity: .14`。

### 1.8 Hover

`hover = {fraction, recordIndex}` 每次 pointermove 更新。2px 品牌色 `hoverLine` **只在空白处**
显示（`hover.recordIndex === null && draft === null`），`left: clamp(0px, var(--trajectory-hover-left) - 1px, 100% - 2px)`。
在 span 上则 span 自身亮起（`data-hovered`）并出 `Tooltip`（`delayMs = 500`，`side="bottom"`），三行：

```
TOOL
14:22:03.117 → 14:22:04.902
Total 1,785 ms · TTFT 213 ms · Decoding 1,572 ms
```

时间 `toLocaleTimeString` 带毫秒，时长整数 ms 千分位（`trajectory-record.ts:117-121`）。

### 1.9 增长与跟随

上游没有尾部跟随（全域始终塞进容器）：

- 未缩放：新事件让 `model.end` 增长 → **已有 span 变窄**，全部可见。
- 缩放中：`viewport` 用域单位保存，窗口锁定在同一批记录，新事件落在右侧屏外；
  仅当窗口完全落出新模型时重置为 null（`:280-287`）。
- 唯一自动平移：`selectedIndex` 变到窗口外时，**最小距离**平移露出它并开 180ms `ease-out`
  的 `left` 过渡（`:288-310`；`@media (prefers-reduced-motion: no-preference)`），宽度从不动画。
- 已提交选区落出新模型时自动清除（`:271-279`）。

### 1.10 更早历史

仅当 `hasEarlierRecords && domainStart === model.start` 时显示（`:324, 603-609`）；平移走就隐藏，
不给未知历史造宽度。左缘 28px 按钮，`linear-gradient(to right, bg-layer-2 0, 38%, transparent)`，
`opacity .72 → 1`，字形 `…`，tooltip `side="right"` 500ms；加载中变禁用态。

### 1.11 常量

`MINIMUM_DRAG_PX 3` · `MINIMUM_ZOOM_OPERATIONS 4` · `EDGE_PAN_ZONE_FRACTION 0.08` ·
`EDGE_PAN_STEP_FRACTION 0.025` · `MAXIMUM_EDGE_PAN_PX 32` · `TIMELINE_TOOLTIP_DELAY_MS 500` ·
缩放因子 `exp(deltaY*0.0015)` · 全域吸附 `0.999` · plot 50px · 标签槽 44px · 道距 14px ·
条 8px/圆角 1px/最小 2px · 视口过渡 180ms ease-out。

## 2. 账本行

两列 `table-layout: fixed`（`TrajectoryTable.module.css:119-141`）：`.eventColumn` **122px**
（容器查询 `@container trajectory-table (max-width: 620px)` 下 **50px**），内容列自动。基准字号
`--dsw-font-xxs-12`（12px/18px）。

**行高按类固定，不测量**（`trajectory-virtual-rows.ts:6-8`）：内容行 30px · 折叠摘要 20px ·
`requestOnly` 分隔 0px · 末端分隔 9px · 加载历史行 30px。

**左槽**（`td.event`，`padding-left: 36px`/紧凑 28px，`overflow: visible`）叠放：
① 请求圆点按钮（§4）；② `.turnRail` 2px 竖轨，仅当前活跃 turn 显示；③ `.selectionRail` 3px 品牌色轨（选中行）；
④ `.turnLabel` 角标贴在 turn 首行左上（`padding 1px 5px; border-radius 0 0 2px; font 8px/10px code; tabular-nums`），
`Turn 7 ↔ #7` 用 `inline-grid` 叠层做 max-width 64px↔0 + opacity 交叉淡入；⑤ `.kindSlot`（76px 右对齐）→ `.kindTag` 徽章。

**类型徽章**：`height 19px; padding 0 5px; radius 4px; font 10px/16px; weight 650; letter-spacing .035em`。
标签由字典键 `kind.*` 提供（`TrajectoryTable.tsx:40-48`）。紧凑模式下文字折叠（`max-width 72px → 0`）、
13px 图标展开（`width 0 → 13px; scale(.8) → 1`），得到 19×19 图标方块，带 `side="right"` tooltip；
全部 `180ms var(--ds-ease-in-out)`。

**内容格**：单行 `text-overflow: ellipsis`，`title` 带全文 `request → result`。工具行两列 grid
（`.resultPreview`）：`grid-template-columns: clamp(180px, var(--trajectory-tool-request-width, calc(36cqw - 56px)), 480px) minmax(0,1fr); gap: 8px`，
调用与 `→ result` 各自省略。工具行用代码字体；调用名与参数不同字体/颜色。
空文本但带图片的记录显示 `Images ×N`（`layout.ts:127-131, 799, 1068, 1095`）。

**行状态**：hover `--dsw-alias-interactive-bg-hover`；选中 `--dsw-alias-interactive-bg-active` + `aria-selected`；
时间轴聚焦之外 `opacity: .24`；过渡 `background-color 120ms, opacity 120ms`。turn 分隔线由
`tr[data-turn-start] td::before` 画 2px 并 `translateY(-50%)` 骑在行界上。
`<tr>` 携带 `data-kind / data-record-index / data-request-only / data-group-start / data-turn-start /
data-turn-end / data-error / data-running / data-collapsed-summary / data-selected / data-timeline-focus`
等 14 个状态属性（`:2433-2451`），由 `stateOf()`（`:713-721`）集中派生。

**键盘**：行 `tabIndex=0`（分隔行 −1），`Enter`/`Space` = 点击；`focus-visible` 内描边 1px 品牌色。
**没有方向键导航。** 行 `aria-label` 由模板拼出（`request.rowAria` 等）。

## 3. 分组与折叠

### 3.1 数据分组

`layout.ts` 把快照折成 `TrajectoryTurnModel { turn: number|null, groups: [{title, cells}] }`，
组标题为 `group.message` / `group.step`（`{step}`），`turn: null` 的段是独立 compaction，显示为
"Between turns"。`flattenRecords`（`TrajectoryTable.tsx:436-461`）线性化并打 `groupStart / turnStart / turnEnd`。

**没有表头行**：turn 靠 2px 分隔线 + 首行角标，请求/step 靠左槽圆点。

### 3.2 两个独立折叠维度

状态在 `TrajectoryView`，默认全展开、不持久化：`collapsedTurns: Set<number>`、
`collapsedAssistants: Set<recordId>`。

- **折叠 turn**（`collapseTurnRecords`）：保留该 turn 首条内容行 + 一条 20px 摘要行，其余丢弃。
  摘要 = `summary.steps` + `summary.toolCalls`（如 "3 steps · 7 tool calls"）。`requestOnly` 分隔与
  `system` 行不受折叠影响；只有 ≤1 条内容行的 turn 不可折叠。**step 计数来自 session 提供的
  `requestNumbers` 分组集合**（`:1864-1866`），不再解析标题字串；未知分组计 0 steps。
- **折叠调用**（`collapseAssistantRecords`）：某 assistant 行折叠时，其后连续的 `tool` 行替换为一条
  20px 摘要："4 tool calls · bash, read, edit"（去重工具名）。
- 工具栏 Turns/Calls 按钮对全部可折叠项切换，全部已折叠时翻转为全展开（`TrajectoryView.tsx:409-440`）。
- 顺序：先 turn 后 assistant（`:1760-1768`）。

### 3.3 交互

- 点击摘要行 → 展开该维度；摘要行 `cursor: pointer`，不可选中。
- **双击普通行**按上下文切换：在已折叠 turn 内 → 展开 turn；assistant 且有工具调用 → 切换其调用；
  turn 首行 → 折叠 turn（`:2343-2366`）。
- **检查时自动展开**：`openRecordSummary` 展开所属 turn，tool 行还会回溯到 assistant 一起展开，
  再选中并排队滚动。
- **搜索绕过折叠**：`searchMatchIndexes !== null` 时直接 `filterRecords`，不做折叠；过滤序列重算
  `groupStart/turnStart/turnEnd` 让分隔线仍正确。

### 3.4 与虚拟化共存

`@tanstack/react-virtual`，`hasOlderRecords || records.length > 100` 时启用（`:1774-1775`）。
配置：`estimateSize` 读已知行高表、`getItemKey` 语义键、`anchorTo: 'end'`、`overscan: 12`、
`initialRect.height: 600`、有加载行时 `scrollMargin: 30`。

值得照抄的技巧：① 零高行不成为虚拟项——`groupTrajectoryVirtualRows` 把 `requestOnly` 分隔挂到下一
内容行，尾部一串合成一个 9px 项；② `useStableVirtualRowStructure` 在所有 `{key,height}` 不变时返回同一
数组引用，流式内容更新不触发重测/重滚；③ 用两个占位 `<tr>`（`--trajectory-virtual-spacer-height`）
而非绝对定位，保住 `<table>` 语义与 `aria-rowindex/aria-rowcount`；④ 折叠改高度（30→20）但键稳定
（`trajectoryVirtualRecordKey` 追加 `\0summary\0turn|assistant`）。

## 4. 请求圆点

`.requestBoundaryControl`（css `:232-321`，渲染 `TrajectoryTable.tsx:2381-2403`）：

- 在左槽，**绝对定位 `top: -8px`**，16px 命中区骑在上一行与请求首行的边界上；
  `left: calc(12px + var(--request-boundary-offset))`（紧凑 6px）。
- 可见点是 `::before` **5px 圆**，`box-shadow: 0 0 0 2px <bg-layer-1>` 把它从行线里抠出来。
- **同位置多个请求横向扇出**：`--request-boundary-offset = runIndex * 8px`。
- 代表一次模型请求（`Request #N`，session 内全局编号，含 compaction）。**身份是**
  `assistant\0turn\0step` / `compaction\0seq`（`:530-534`），选中态跨语言/标签变更稳定；
  session 没给编号的分组**不画圆点**（不再合成）。
- hover/focus：点变品牌色并露出 `::after` 标签片（`content: attr(data-label)`，9px/12px 代码字体，
  1px 边框，`0 2px 6px rgba(0,0,0,.12)`，`opacity 0→1` + `translateX(-2px)→0`，120ms）——纯 CSS tooltip；
  点被 hover 时行 hover 底色被抑制。
- active（其请求在检查器打开）：18% 品牌填充 + `0 0 0 1.5px` 环；error：`--dsw-alias-state-error-primary`。
- 点击 `stopPropagation` 并打开**请求**检查器（与行选中是两种选中）。

## 5. 检查器

- **右侧推挤面板**，不是浮层：`<aside class=details>` 是表格面板的 `flex: none` 兄弟（css `:864-875`），
  表格变窄（可能触发容器查询进入紧凑槽）。
- 默认宽 `clamp(320px, 38%, 440px)`，`max-width: calc(100% - 280px)`；左缘 8px 隐形把手
  `cursor: col-resize`，拖动限 **320–720px** 且表格至少 280px；**双击复位**；`ArrowLeft/Right` ±16px。
  拖动同时更新 `--trajectory-tool-request-width`（`calc(58cqw - offset)`），账本工具行的
  调用/结果分栏跟着走，不跳变。
- 头 42px：徽章（或圆点 + `Request #N`）+ 位置 `Turn 3 · Step 2`（11px 代码字体）+ 28px 关闭。
- tab 条 34px，横向可滚、隐藏滚动条；激活 tab 品牌色 + 2px 下划线（左右内缩 9px）。
- **tab 集**（`:894-923`, `:209-224`）：记录 user/context/assistant：`Summary · Preview · Raw · (Source)`；
  tool：`Summary · (Payload) · (Result) · Schema · Timing`；compacted：`Summary · Raw Output`；
  system：`(Diff) · System Prompt · Tools`（Diff 仅当替换了前一个 prompt）；请求：`Summary · Options · Usage · Timing`
  （Options 未记录则隐藏）。tab 选择按 session 用 MRU 记忆，回退到首个可用 tab。
- **Summary tab** 是组合页：`<dl>`（Status/Provider/Model/Tokens/层级链接）+ `OverviewSection` 卡片
  （Preview/Payload/Result/Schema/Usage/Timing/Request Timing），卡片标题是跳到对应 tab 的按钮。
  层级链接：Request # ↔ Assistant Message ↔ Tool Call；assistant 的工具调用 chip 打开对应 tool 记录。
- **Diff** = 两个 prompt 快照之间 system/tools 的变化，`structuredPatch`（`diff` 包，`context: 3`），
  渲染为 `@@ -a,b +c,d @@` hunk，11px/17px 代码字体，增删行底色。
- 失败文案由稳定 code 本地化：`errorCode === 'AUTH'` → `details.failure.auth`（原始报错不进 UI 状态）；
  `COMPACTION_INTERRUPTED_ERROR` 哨兵 → `layout.compactionInterrupted`；其余显示原文（`:729-737`）。
  图片-only 的错误结果保留错误文本（`ToolOutputBlocks.errorDetail`）。
- 图片通过 `renderImages({images, align:'start'})` 渲染槽输出（上游已删内联 `<img>`）；**未提供渲染函数则不显示图片**。
- Summary 滚动区滚动条 thumb 透明，hover/focus-within 才显示（几何保留、外观隐藏）。
- 关闭：× 按钮，或点击账本空白（`event.target === currentTarget`），同时清时间轴选区。

## 6. 工具栏

32px sticky，`role="toolbar"`。**没有统计数字**——"时长/轮次/调用"是三个开关按钮：

- **Duration**（`aria-pressed`，12px 时钟图标）：`actualDuration` 切换 → 时间轴 `sequence ⇄ duration`。
  上游持久化到浏览器（`dsh.trajectory.duration`），默认 false。切换时**清除时间轴选区**（域单位变了）。
- **Turns / Calls**（`⊟/⊞`）：两个折叠维度的全部折叠/展开。
- 隐藏的 Actual-time 开关（20×10 轨道，6px 滑块，`translateX(10px)`，120ms）。
- **搜索框**：`flex: 0 1 164px`，最小 84px，高 22px，`margin-left: auto`，`type="search"`，圆角 4px，
  focus-within 品牌边框。行为是**实时过滤**：每次按键设 query，表格只剩匹配行，时间轴非匹配 span
  压到 `.14`。无计数、无上下条。
- 搜索索引（`trajectory-search-index.ts`）：按记录增量索引 turn 标签、组标题、kind（含 `assistant` 别名）、
  文本、markdown 预览、输入/输出/thinking/schema、结果、callId、各 block 字段、JSON 化的消息源与 prompt 快照；
  小写；query 空格分词 **AND** `includes`。首次建索引后重建节流 **3000ms**（`TrajectoryView.tsx:33, 297-312`）。

## 7. 聚焦 / 选中 / 检查模型

| 概念 | 归属 | 效果 |
|---|---|---|
| **Range**（时间轴选区） | `TrajectoryView.timelineSelection` | 推导 `timelineFocusIndexes` |
| **Focus**（一组行） | 派生 | 行得到 `data-timeline-focus="inside|outside"`；outside **压暗到 .24 但留在列表**；表格自动滚动 |
| **Selection / inspect**（一条记录或一个请求） | `TrajectoryTable.selectedRecordId` \| `selectedRequest` | 行高亮 + 轨 + 打开检查器；回传时间轴做 `data-current` 环 |
| **Search matches** | `searchMatchIndexes` | 过滤表格、压暗 span |

流程：时间轴拖选 → `onRangeChange` → `trajectoryTimelineFocusIndexes`（`span.start <= range.end && span.end >= range.start`）→ 表格；
时间轴点 span → `onRecordSelect` → 清 range，`timelineRecordSelection` 以**新对象**下发（一次性命令，表格按引用去重）→ 选中 + 检查器 + 滚动；
时间轴点空白 → `onRecordFocus` → 只滚动；表格点行 → `selectRecord` → 若该记录在当前聚焦集之外则**清 range**；
选中索引回流到时间轴 → `data-current` 环 + 最小距离自动平移。

**滚动到聚焦**（`:2070-2136`）：聚焦块高于面板 → 首行 `align: 'start'`；否则**中位行** `align: 'center'`；
`behavior: 'smooth'`；虚拟与非虚拟两条路径。任何程序化滚动都把 `followsTableTail = false`。

**尾部跟随**（`:2159-2189, 2201-2207`）：每次 scroll 计算 `scrollHeight − clientHeight − scrollTop <= 2px`；
新数据到来仅在该标志为真时滚到底。首次挂载等 `historyLoading` 结束后 `behavior:'auto'` 跳到底，
之后才显示表格（`.table:not([data-scroll-ready]) { visibility: hidden }`）——看不到"跳到底"。

## 8. 加载更早历史

两处入口、一个动作 `onLoadOlder(): Promise<boolean>`：

- **表格**：永久首行（`aria-rowindex=1`，30px）全宽按钮 "Load earlier history"，加载中变禁用 +
  10px spinner，`role="status" aria-live="polite"` 播报；该行不画 turn 分隔。
- **时间轴**：`…` 控件（§1.10）。
- **自动触发**：scroll 时 `scrollTop <= 48` 触发，`loadingOlder` ref + prop 防重入。
- **前插锚定**：请求前记 `{historyStartSeq, scrollTop, scrollHeight}`；`useLayoutEffect` 中
  非虚拟路径恢复 `scrollTop = old + (newScrollHeight − oldScrollHeight)`；虚拟路径靠 `anchorTo: 'end'` +
  稳定 `getItemKey`。两条路径都关闭尾部跟随。
- 初始加载：sticky 零高条覆盖一条 30px "Loading trajectory…"。

## 9. 在线 / 半截状态

- 结构与内容分离：时间轴收到**去内容**的 partial 副本（blocks 清空、tool-call id 保留），只在形状变化时重渲；
  表格收到完整 `streamingCells`，按索引覆盖行的 `cell`。键与行高不变 ⇒ 不重测、不重滚。
- 运行中行 `data-running`（tool 无 `outputDetail`，或 compaction `timeSeconds === null`）——**没有对应 CSS**：
  无 spinner、无脉冲；可见信号只是缺 `→ result` 段和检查器里的 `Status: Pending`。账本唯一动画是
  700ms 线性历史 spinner（`prefers-reduced-motion` 下关闭）。
- 时间轴：运行中记录时长 0 ⇒ 2px 起点标记。
- 错误：行与 span 都打 `data-error`（error 色轨、`--dsw-alias-state-error-primary` span、红色 payload/JSON 树）。
- 上游支持打包分片事件 `chunkrow/{text,reasoning,tool-call}-chunks`，按 `data.dt` 重建每片的首可见时刻，
  TTFT 不因打包失真。klaude 事件不打包，忽略。

## 10. 视觉常量与 token 角色

**字体**：`--dsw-font-xxs-12`（12px/18px，账本、工具栏）· `--dsw-font-xs-13`（13px/20px，检查器、tab）·
`--dsw-font-xs-strong-13`（500 13px/20px，检查器标题）· `--dsw-font-xxxs-11`（11px/14px，tooltip）·
`--ds-font-family-code`（`'SF Mono','JetBrains Mono','Fira Code',Consolas,…`：工具名/参数、角标 8px/10px、
请求标签 9px/12px、diff 11px/17px、检查器位置 11px/16px）· 泳道标签 10px · 徽章 10px/16px w650。
ui-theme **没有 `@font-face`**，全部系统字体栈；唯一 webfont 是 KaTeX 随 `katex.min.css`。

**颜色角色**：`--dsw-alias-bg-layer-1` 页面/账本 · `-bg-layer-2` 时间轴 plot、搜索框 ·
`-bg-module-platform` 角标、diff 元信息 · `-border-l1` 行线/turn 线 · `-border-l2` 分区边框 ·
`-label-primary/-secondary/-tertiary/-caption/-dimmed` 五级文字 · `-interactive-bg-hover/-active` 行 hover/选中 ·
`-state-business-primary` **选区/聚焦/品牌强调** · `-brand-primary-new-colorprimary-new-color` 圆点与轨 ·
`-state-success-primary/-tertiary` CONTEXT、diff 增行 · `-state-warn-label/-tertiary` TOOL ·
`-state-error-primary/-secondary` 错误 · assistant 色 = `color-mix(brand 60%, error-secondary)`（紫），
底色为其 15% 叠 layer-1 · `--trajectory-turn-accent = color-mix(blue-500 22%, bg-layer-1)` · `--dsw-alias-scrollbar-bg-l2/-hover-l2`。
ui-trajectory 的四个 CSS 文件共消费 40 个 theme/`--dsh` token，全部由 `ui-theme/src/styles/{base,design-platform}.css` 定义。

**几何**：工具栏 32 · 时间轴 50（标签 44、道距 14、条 8×min2、圆角 1）· 行 30 / 摘要 20 / 分隔 0 / 末端 9 ·
左槽列 122 → 50 · kindSlot 76 → 19 · 徽章高 19 圆角 4 · 圆点 5（命中 16、环 2、扇出 8）· 轨 2/3 ·
检查器头 42、tab 34、宽 clamp(320, 38%, 440)、拖 320–720、表格最小 280、步进 16 ·
工具行分栏 `clamp(180px, 36cqw−56px, 480px)` 间距 8。

**动效**：`--ds-ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)`；120ms（行/点/tab/底色）、180ms（紧凑槽变形；
时间轴视口 `left` 用 `ease-out`）、700ms 线性（spinner）。装饰性动效全部包在
`@media (prefers-reduced-motion: no-preference)`。

两个布局变量：`--dsh-trajectory-toolbar-height: 32px`、
`--dsh-trajectory-bottom-clearance: calc(var(--dsh-composer-height, 152px) + 16px)`（`views.module.css:3, 27`），
后者作为表格与检查器的 `padding-bottom`，防止浮动输入框盖住末行。

## 11. 未变更核对（`47f943859b` → `cd5ef8148158`）

上游两版之间 `TrajectoryTimeline.module.css`、`TrajectoryToolbar.*`、`trajectory-virtual-rows.ts`
**零改动**；`TrajectoryTimeline.tsx`/`timeline.ts` 只有 i18n。改动集中在：全量 i18n（每个字串进
`trajectory` 字典，zh/en 各 174 键）、图片改渲染槽（删内联 `<img>` 与 URL 嗅探）、请求身份从标题字串
改为 `assistant\0turn\0step`、`errorCode` 本地化失败文案、打包分片流。行类型集、tab 集、折叠维度、
交互词汇**均无增减**。

## 12. klaude 刻意偏离

以下是 klaude fork 与上游的全部差异；不在此列的行为以上文为准。

| # | 偏离 | 上游 | klaude | 原因 |
|---|---|---|---|---|
| D1 | 泳道尺度模型 | 全域塞进容器；缩放/平移改域窗口；未缩放时记录越多每条越窄 | **已实现（M3）**：`contentWidth = max(W, fullDuration × p)`，`p` 默认 `6 px/记录`（sequence）或 `0.004 px/ms`（duration，240px/分钟），夹在 `[W/fullDuration, W/min(4 记录 \| 20ms, fullDuration)]`；track `overflow-x: auto`；滚轮 `p' = p × exp(−deltaY × 0.0015)` 并按光标锚点换算 `scrollLeft`（横向 deltaX 直接滚动）；右键拖动与原生滚动条改 `scrollLeft`；距右缘 ≤2px 时跟随新记录；选中项变更时最小距离滚动露出（180ms ease-out）；加载更早历史按新增宽度补 `scrollLeft`；`…` 按钮仅在 `scrollLeft === 0` 显示，且首次挂载钉在尾部；框选/hover/tooltip/双击/Esc/空闲压缩不变；缩放按模式各自记忆。数学在 `timeline.ts` 纯函数，常量见 `web/src/trajectory/README-timeline.md` | 作者要求记录多时不压窄、可直接横滚 |
| D2 | 行类型 | 7 种：system/user/context/compacted/message/tool/subtool | 删 `subtool`；新增 `rewind`（仅旧会话）与 `btw` | klaude 无 run_code 子派发；有 `/btw` 侧问与历史 `RewindEntry` |
| D3 | 丢弃行 | 无概念 | 行级 `data-discarded`：置灰 + 划线，留在原位；状态由 server 一遍扫描下发（retracted/compacted/rewound） | append-only 账本必须可视被丢弃内容 |
| D4 | sub-agent | 无 | 不嵌套。子会话是列表页独立行（parent badge，可按父折叠）；父轨迹 Agent 工具 TOOL 行的检查器有"打开子会话"链接 | 简化；子会话本身就有完整 `events.jsonl` |
| D5 | 图片渲染槽 | 由宿主插件注册，未注册不显示 | 我们实现 `renderImages`：URL 直连，本地图经 `/api/web/file` | viewer 无插件系统 |
| D6 | 类型徽章文案 | zh 字典为中文（系统/用户/…） | `kind.*` 改回英文（SYSTEM/USER/CONTEXT/COMPACTED/ASSISTANT/TOOL/REWIND/BTW） | 决策 #4 |
| D7 | 时长偏好持久化 | zustand 快照 store `dsh.trajectory.duration` | `localStorage` 同名键 | 去掉 zustand/immer |
| D8 | 底部留白 | `--dsh-composer-height` 由 composer 注入，回退 152px | 回退改为 0（viewer 无输入框） | 只读 |
| D9 | 请求编号 | 由 session 快照提供 | 适配器按 step 顺序生成；compaction/btw/fork 独立编号 | 上游未知分组不画圆点，必须全量提供 |
| D10 | 打包分片流 | 支持 `chunkrow/*` | 不需要 | klaude 事件不打包 |
| D11 | 冷会话进行中状态 | 始终来自在线快照 | 未加载会话无 `partial`/`runningCalls`，只有落定行 | 冷会话不初始化 agent |
