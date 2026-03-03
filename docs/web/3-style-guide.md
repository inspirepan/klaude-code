# Web UI Style Guide

参考：Claude.ai 界面风格（暖色调、极简），但不使用 serif 字体。

MVP 仅实现 Light 模式，Dark 模式后续迭代。

---

## 1. 色板

以 Claude.ai 的暖米色调为基础，适配 Tailwind CSS 变量系统。

### 核心色

| Token | Hex | 用途 |
|---|---|---|
| `--background` | `#F5F5F0` | 页面背景（暖灰白） |
| `--surface` | `#FFFFFF` | 卡片、输入框、弹窗背景 |
| `--surface-secondary` | `#EEEEE8` | 侧边栏背景、次级面板 |
| `--primary` | `#ae5630` | 主色调（暖赤陶橙），发送按钮、链接、高亮 |
| `--primary-hover` | `#c4633a` | 主色调 hover 态 |
| `--primary-foreground` | `#FFFFFF` | 主色调上的文字 |

### 文字色

| Token | Hex | 用途 |
|---|---|---|
| `--foreground` | `#1a1a18` | 主文字（近黑暖色） |
| `--foreground-secondary` | `#6b6a68` | 次要文字（时间戳、摘要、placeholder） |
| `--foreground-muted` | `#9a9893` | 更弱文字（禁用态、提示） |

### 功能色

| Token | Hex | 用途 |
|---|---|---|
| `--user-bubble` | `#DDD9CE` | 用户消息气泡背景 |
| `--border` | `rgba(0,0,0,0.08)` | 通用边框（`#00000015`） |
| `--border-strong` | `rgba(0,0,0,0.15)` | 强调边框 |
| `--error` | `#DC3545` | 错误文字、错误边框 |
| `--success` | `#28A745` | 成功状态、diff add 行标记 |
| `--warning` | `#E8A317` | 警告状态 |

### Diff 色

| Token | Hex | 用途 |
|---|---|---|
| `--diff-add-bg` | `#DAFBE1` | diff 新增行背景 |
| `--diff-add-text` | `#1F6B2B` | diff 新增行前景 |
| `--diff-remove-bg` | `#FFD7D5` | diff 删除行背景 |
| `--diff-remove-text` | `#9A1B1B` | diff 删除行前景 |
| `--diff-ctx-bg` | transparent | diff 上下文行背景 |

> Diff 组件使用 `@pierre/diffs` 自带主题（`pierre-light`），以上色值仅在自定义场景覆盖。

---

## 2. 字体

### 正文字体（Sans）

```css
--font-sans: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
```

使用 Inter 作为默认字体。通过 Google Fonts 或 `@fontsource/inter` 引入。

### 等宽字体（Mono）

```css
--font-mono: 'TX-02', ui-monospace, 'SF Mono', 'Cascadia Code', monospace;
```

使用 TX-02 作为等宽字体。字体文件放置在 `web/public/fonts/` 下：

```css
@font-face {
  font-family: 'TX-02';
  src: url('/fonts/tx-02.woff2') format('woff2');
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'TX-02';
  src: url('/fonts/tx-02-bold.otf') format('opentype');
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'TX-02';
  src: url('/fonts/tx-02-italic.otf') format('opentype');
  font-weight: 400;
  font-style: italic;
  font-display: swap;
}

@font-face {
  font-family: 'TX-02';
  src: url('/fonts/tx-02-bold-italic.otf') format('opentype');
  font-weight: 700;
  font-style: italic;
  font-display: swap;
}
```

### 字号

| 用途 | Tailwind class | 大小 |
|---|---|---|
| 正文 / 消息文本 | `text-sm` | 14px |
| 代码块 | `text-[13px] font-mono` | 13px |
| 侧边栏 session 标题 | `text-sm font-medium` | 14px |
| 侧边栏时间/摘要 | `text-xs` | 12px |
| 状态栏 | `text-xs` | 12px |
| 标题 (h1-h3 in markdown) | `text-lg` / `text-base` / `text-sm font-semibold` | 18/16/14px |
| ToolCall mark + name | `text-sm font-medium font-mono` | 14px |
| Raw JSON 查看器 | `text-[13px] font-mono` | 13px |

---

## 3. 间距与布局

### 全局布局

```
┌──────────────────────────────────────────────────┐
│  LeftSidebar (260px)  │  Main Content            │
│                       │  ┌──────────────────────┐ │
│  [搜索框]              │  │  MessageList         │ │
│  [session 列表]        │  │  (max-w: 768px)      │ │
│                       │  │  (居中)               │ │
│                       │  └──────────────────────┘ │
│                       │  ┌──────────────────────┐ │
│                       │  │  InputArea           │ │
│                       │  │  (sticky bottom)     │ │
│                       │  └──────────────────────┘ │
│                       │  [StatusBar]              │
└──────────────────────────────────────────────────┘
```

| 区域 | 值 |
|---|---|
| 侧边栏宽度 | `260px` |
| 消息流最大宽度 | `768px`，水平居中 |
| 消息流内边距 | `px-4 py-2`（16px / 8px） |
| 消息间距 | `space-y-4`（16px） |
| 卡片内边距 | `p-3`（12px） |
| 卡片圆角 | `rounded-xl`（12px） |
| 输入框圆角 | `rounded-2xl`（16px） |

### 阴影

```css
/* 输入框 / composer */
--shadow-composer: 0 0.25rem 1.25rem rgba(0, 0, 0, 0.035);

/* 卡片悬浮 */
--shadow-card-hover: 0 2px 8px rgba(0, 0, 0, 0.06);
```

---

## 4. 组件样式要点

以下不是完整定义，仅记录关键样式决策。

### 侧边栏

- 背景 `--surface-secondary`
- 顶部 `New Session` 按钮：主色实底（`bg-primary text-primary-foreground`），高度 `h-8`，圆角 `rounded-lg`，全宽
- Session 卡片：hover 时 `bg-white/60`，选中态 `bg-white` + 左边框 `border-l-2 border-primary`
- 项目分组标题：`text-xs font-semibold uppercase tracking-wider text-foreground-secondary`

### 消息气泡

- 用户消息：`bg-[--user-bubble]` 圆角气泡，右对齐或左对齐均可（参考 Claude.ai 为左对齐全宽）
- Assistant 消息：无背景色，直接渲染 markdown（与 Claude.ai 一致）
- 两者均左对齐，不做聊天式左右分列

### ToolCall / ToolResult

- 背景 `--surface`，边框 `--border`
- 折叠态：单行显示 `[mark] Name details`，无背景
- 展开态（Raw JSON / diff）：带边框卡片

### 输入框

- 背景 `--surface`
- 阴影 `--shadow-composer`
- 圆角 `rounded-2xl`
- 内部按钮组（附件、模型选择、发送）底部排列

### 代码块（markdown 内）

- 背景 `#F8F8F5`（暖灰白，比页面背景略浅）
- 圆角 `rounded-lg`
- 行号颜色 `--foreground-muted`
- 右上角 copy 按钮 + 语言标签

### Sub-agent 卡片

- 左侧竖线 `3px solid`，颜色按序号从预设色板轮转
- 预设色板：`#ae5630`（橙）、`#6366f1`（靛蓝）、`#0891b2`（青）、`#7c3aed`（紫）、`#059669`（绿）
- 卡片内部间距与主消息流一致

### 状态栏

- 固定底部，高度 `28px`
- 背景 `--surface-secondary`
- 文字 `--foreground-secondary` + `text-xs`
