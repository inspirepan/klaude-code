import type { Translations } from "./en";

const zh: Translations = {
  // Sidebar
  "sidebar.new": "新建",
  "sidebar.collapseSidebar": "收起侧栏",
  "sidebar.expandSidebar": "展开侧栏",
  "sidebar.archiveStale": "归档过期会话",
  "sidebar.archivedSessions": "已归档会话",
  "sidebar.archived": "已归档",
  "sidebar.noArchivedSessions": "没有已归档的会话",
  "sidebar.sessionArchived": "会话已归档",
  "sidebar.undo": "撤销",
  "sidebar.undoArchive": "撤销归档",
  "sidebar.resizeSidebar": "调整侧栏宽度",
  "sidebar.loadFailed": "加载失败",
  "sidebar.clickToRetry": "点击重试",
  "sidebar.loading": "加载中\u2026",
  "sidebar.noSessions": "暂无会话",
  "sidebar.noSessionsHint": "点击上方「新建」开始",
  "sidebar.archiveSession": "归档会话",
  "sidebar.unarchiveSession": "取消归档",
  "sidebar.newSession": "新会话",
  "sidebar.newSessionIn": (workDir: string) => `在 ${workDir} 中新建会话`,
  "sidebar.loadMore": (count: number) => `加载更多 (${count})`,
  "sidebar.showLess": "收起",
  "sidebar.searchSessions": "搜索会话",
  "sidebar.searchPlaceholder": "搜索会话...",
  "sidebar.noSearchResults": "没有匹配的会话",

  // Archive cleanup
  "archiveCleanup.confirmTitle": (count: number) => `归档 ${count} 个会话？`,
  "archiveCleanup.confirmDesc": "归档超过 1 天或没有变更的会话。",
  "archiveCleanup.archiving": "正在归档超过 1 天或没有变更的会话",
  "archiveCleanup.noEligible": "没有超过 1 天或没有变更的会话",
  "archiveCleanup.tooltip": (count: number) => `归档 ${count} 个超过 1 天或没有变更的会话`,
  "archiveCleanup.cancel": "取消",
  "archiveCleanup.archive": "归档",

  // Composer
  "composer.placeholder": "发送消息...",
  "composer.followUpPlaceholder": "发送后续消息...",
  "composer.draftPlaceholder": "我们要做什么？",
  "composer.send": "发送",
  "composer.sending": "发送中",
  "composer.interrupt": "中断",
  "composer.addImage": "添加图片",
  "composer.removeImage": "删除图片",
  "composer.addImageTooltip": "添加图片或从剪贴板粘贴",
  "composer.unsupportedImage": "仅支持 PNG、JPEG、GIF 和 WebP 格式的图片。",
  "composer.uploadingImage": "正在上传图片...",
  "composer.uploadingImages": (count: number) => `正在上传 ${count} 张图片...`,
  "composer.compactDesc": "清除上下文，保留摘要",
  "composer.readOnlyPlaceholder": "只读 \u2014 此会话由另一个运行时拥有",

  // New session overlay
  "newSession.title": "开始新会话",
  "newSession.subtitle": "选择工作区，然后发送第一条消息。",
  "newSession.loadModelsFailed": (error: string) => `加载模型失败：${error}`,
  "newSession.modelSwitchFailed": (error: string) => `切换模型失败：${error}`,

  // Workspace picker
  "workspace.label": "工作区",
  "workspace.hint": "选择或输入本地路径",
  "workspace.placeholder": "/path/to/workspace",
  "workspace.toggle": "切换工作区建议",
  "workspace.noMatch": "未找到匹配的目录。按回车使用此路径。",
  "workspace.navigate": "导航",
  "workspace.fill": "填充",
  "workspace.select": "选择",

  // Model selector
  "model.selectModel": "选择模型",
  "model.defaultModel": "默认模型",
  "model.filterPlaceholder": "筛选模型...",
  "model.loading": "加载模型中...",
  "model.default": "默认",

  // Status
  "status.running": "运行中 \u2026",
  "status.waitingInput": "等待输入 \u2026",
  "status.compacting": "压缩中 \u2026",
  "status.thinking": "思考中 \u2026",
  "status.typing": "输入中 \u2026",

  // Messages header
  "header.backToMain": "返回主会话",
  "header.collapseAll": "全部折叠",
  "header.expandAll": "全部展开",
  "header.search": "搜索",
  "header.searchMessages": "搜索消息",
  "header.subAgent": "子 Agent",
  "header.readOnly": "只读 \u2014 此会话由另一个运行时拥有",

  // Error
  "error.title": "错误",
  "error.retryAvailable": "可以重试",

  // Interrupt
  "interrupt.message": "已被用户中断",

  // Thinking
  "thinking.label": "思考过程",

  // Compaction
  "compaction.label": "已压缩",
  "compaction.showMore": "展开更多",
  "compaction.showLess": "收起",

  // Rewind
  "rewind.label": (checkpointId: number) => `已回退到检查点 ${checkpointId}`,
  "rewind.rationale": "原因：",
  "rewind.note": "上下文：",
  "rewind.showMore": "展开更多",
  "rewind.showLess": "收起",

  // Question summary
  "question.label": "问题",
  "question.noAnswer": "（未提供回答）",

  // Tool result
  "toolResult.noContent": "（无内容）",
  "toolResult.showLess": "收起",
  "toolResult.showMore": (count: number) => `展开更多 (${count} 行)`,
  "toolResult.linesHidden": (count: number) =>
    `\u00b7\u00b7\u00b7 隐藏了 ${count} 行 \u00b7\u00b7\u00b7`,

  // Sub agent
  "subAgent.defaultDesc": (id: string) => `Sub Agent ${id}`,
  "subAgent.fork": "分支",
  "subAgent.toolCall": (count: number) => `${count} 次工具调用`,

  // Developer message
  "developer.mentionedIn": "引用自",
  "developer.attached": "已附加",
  "developer.todoEmpty": "待办列表为空",
  "developer.todoStale": "待办列表近期未更新",

  // Search bar
  "searchBar.placeholder": "搜索\u2026",

  // User interaction
  "interaction.selectMultiple": "（可多选）",
  "interaction.validationHint": "请选择一个选项或输入回复。",
  "interaction.agentQuestion": (count: number) => `Agent 有 ${count} 个问题需要你回答`,
  "interaction.agentNeedsInput": "Agent 需要你的输入",
  "interaction.pending": (count: number) => `${count} 个待处理`,
  "interaction.cancel": "取消",
  "interaction.submit": "提交",
  "interaction.next": "下一个问题",
  "interaction.otherPlaceholder": "其他：请输入内容。",

  // Copy
  "copy.copy": "复制",
  "copy.copied": "已复制",
  "copy.copyButton": "[复制]",
  "copy.copiedButton": "[已复制]",

  // File search
  "fileSearch.searching": "搜索文件中...",

  // Tool block
  "tool.planning": "规划中\u2026",
  "tool.todoTitle": "计划清单",
  "tool.askingQuestion": "编写问题中\u2026",

  // Collapse group
  "collapse.read": "读取",
  "collapse.edited": "编辑",
  "collapse.wrote": "写入",
  "collapse.patched": "补丁",
  "collapse.ran": "执行",
  "collapse.list": "列出",
  "collapse.bashSearch": "搜索",
  "collapse.fetch": "获取网页",
  "collapse.search": "搜索网页",
  "collapse.thoughts": "思考",
  "collapse.completed": "完成",
  "collapse.agent": "Agent",
  "collapse.toolsUsed": (count: number) => `使用了 ${count} 个工具`,

  // User message
  "userMessage.showMore": "展开更多",
  "userMessage.showLess": "收起",

  // Diff view
  "diff.showMore": "展开更多",
  "diff.showLess": "收起",

  // Task metadata
  "taskMeta.interruptedAfter": "中断于",
  "taskMeta.workedFor": "已工作",
  "taskMeta.steps": (n: number) => `${n} 步`,
  "taskMeta.model": "模型",
  "taskMeta.provider": "提供商",
  "taskMeta.inputTokens": "输入 token",
  "taskMeta.cacheRead": "缓存读取 token",
  "taskMeta.cacheHitRate": (pct: number) => `(${pct}% 命中)`,
  "taskMeta.cacheWrite": "缓存写入 token",
  "taskMeta.outputTokens": "输出 token",
  "taskMeta.reasoning": "推理 token",
  "taskMeta.context": "上下文",
  "taskMeta.cost": "费用",
  "taskMeta.duration": "耗时",
  "taskMeta.throughput": "吞吐量",
  "taskMeta.stepsLabel": "步骤",
  "taskMeta.stepsValue": (n: number) => `${n} 步`,
  "taskMeta.via": (provider: string) => `经由 ${provider}`,

  // Message list
  "messageList.scrollToBottom": "滚动到底部",

  // Developer summary
  "developer.summarySkill": (name: string) => `skill:${name}`,
  "developer.summaryFolderList": (n: number) => `${n} 个目录列表`,
  "developer.summaryReread": (n: number) => `${n} 个重读文件`,

  // Plurals
  "plural.memory": (n: number) => `${n} 个记忆`,
  "plural.file": (n: number) => `${n} 个文件`,
  "plural.list": (n: number) => `${n} 个列表`,
  "plural.image": (n: number) => `${n} 张图片`,
} as const;

export default zh;
