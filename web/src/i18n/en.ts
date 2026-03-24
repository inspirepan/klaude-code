const en = {
  // Sidebar
  "sidebar.new": "New",
  "sidebar.collapseSidebar": "Collapse sidebar",
  "sidebar.expandSidebar": "Expand sidebar",
  "sidebar.archiveStale": "Archive stale sessions",
  "sidebar.archivedSessions": "Archived sessions",
  "sidebar.archived": "Archived",
  "sidebar.noArchivedSessions": "No archived sessions",
  "sidebar.sessionArchived": "Session archived",
  "sidebar.undo": "Undo",
  "sidebar.undoArchive": "Undo archive",
  "sidebar.resizeSidebar": "Resize left sidebar",
  "sidebar.loadFailed": "Load failed",
  "sidebar.clickToRetry": "Click to retry",
  "sidebar.loading": "Loading\u2026",
  "sidebar.noSessions": "No sessions yet",
  "sidebar.noSessionsHint": 'Click "New Agent" above to start',
  "sidebar.archiveSession": "Archive session",
  "sidebar.unarchiveSession": "Unarchive session",
  "sidebar.newSession": "New session",
  "sidebar.newSessionIn": (workDir: string) => `New session in ${workDir}`,
  "sidebar.loadMore": (count: number) => `Load more (${count})`,
  "sidebar.showLess": "Show less",
  "sidebar.searchSessions": "Search sessions",
  "sidebar.searchPlaceholder": "Search sessions...",
  "sidebar.noSearchResults": "No matching sessions",

  // Archive cleanup
  "archiveCleanup.confirmTitle": (count: number) => `Archive ${count} sessions?`,
  "archiveCleanup.confirmDesc": "Archive sessions older than 1 day or with no diff.",
  "archiveCleanup.archiving": "Archiving sessions older than 1 day or with no diff",
  "archiveCleanup.noEligible": "No sessions older than 1 day or with no diff",
  "archiveCleanup.tooltip": (count: number) =>
    `Archive ${count} sessions older than 1 day or with no diff`,
  "archiveCleanup.cancel": "Cancel",
  "archiveCleanup.archive": "Archive",

  // Composer
  "composer.placeholder": "Send a message...",
  "composer.followUpPlaceholder": "Send a follow-up...",
  "composer.draftPlaceholder": "What should we do?",
  "composer.send": "Send",
  "composer.sending": "Sending",
  "composer.interrupt": "Interrupt",
  "composer.addImage": "Add image",
  "composer.removeImage": "Remove image",
  "composer.addImageTooltip": "Add image or paste from clipboard",
  "composer.unsupportedImage": "Only PNG, JPEG, GIF, and WebP images are supported.",
  "composer.uploadingImage": "Uploading image...",
  "composer.uploadingImages": (count: number) => `Uploading ${count} images...`,
  "composer.compactDesc": "Clear context, keep summary",
  "composer.readOnlyPlaceholder": "Read-only \u2014 this session is owned by another runtime",

  // New session overlay
  "newSession.title": "Start a new session",
  "newSession.subtitle": "Choose a workspace, then send your first message.",
  "newSession.loadModelsFailed": (error: string) => `Load models failed: ${error}`,
  "newSession.modelSwitchFailed": (error: string) => `Model switch failed: ${error}`,

  // Workspace picker
  "workspace.label": "Workspace",
  "workspace.hint": "Choose or type a local path",
  "workspace.placeholder": "/path/to/workspace",
  "workspace.toggle": "Toggle workspace suggestions",
  "workspace.noMatch": "No matching directory found. Press Enter to use this path.",
  "workspace.navigate": "navigate",
  "workspace.fill": "fill",
  "workspace.select": "select",

  // Model selector
  "model.selectModel": "Select model",
  "model.defaultModel": "Default model",
  "model.filterPlaceholder": "Filter models...",
  "model.loading": "Loading models...",
  "model.default": "default",

  // Status
  "status.running": "Running \u2026",
  "status.waitingInput": "Waiting for input \u2026",
  "status.compacting": "Compacting \u2026",
  "status.thinking": "Thinking \u2026",
  "status.typing": "Typing \u2026",

  // Messages header
  "header.backToMain": "Back to main session",
  "header.collapseAll": "Collapse all",
  "header.expandAll": "Expand all",
  "header.search": "Search",
  "header.searchMessages": "Search messages",
  "header.subAgent": "Sub Agent",
  "header.readOnly": "Read-only \u2014 this session is owned by another live runtime",

  // Error
  "error.title": "Error",
  "error.retryAvailable": "Retry available",

  // Interrupt
  "interrupt.message": "Interrupted by user",

  // Thinking
  "thinking.label": "Thought",

  // Compaction
  "compaction.label": "Compacted",

  // Question summary
  "question.label": "QUESTION",
  "question.noAnswer": "(No answer provided)",

  // Tool result
  "toolResult.noContent": "(no content)",
  "toolResult.showLess": "Show less",
  "toolResult.showMore": (count: number) => `Show more (${count} lines)`,
  "toolResult.linesHidden": (count: number) =>
    `\u00b7\u00b7\u00b7 ${count} lines hidden \u00b7\u00b7\u00b7`,

  // Sub agent
  "subAgent.defaultDesc": (id: string) => `Sub Agent ${id}`,
  "subAgent.fork": "fork",
  "subAgent.toolCall": (count: number) => `${count} tool call${count !== 1 ? "s" : ""}`,

  // Developer message
  "developer.mentionedIn": "mentioned in",
  "developer.attached": "Attached",
  "developer.todoEmpty": "Todo list is empty",
  "developer.todoStale": "Todo hasn't been updated recently",

  // Search bar
  "searchBar.placeholder": "Search\u2026",

  // User interaction
  "interaction.selectMultiple": "(select multiple)",
  "interaction.validationHint": "Please select an option or type a response.",
  "interaction.agentQuestion": (count: number) =>
    `Agent has ${count} question${count === 1 ? "" : "s"} for you`,
  "interaction.agentNeedsInput": "Agent needs your input",
  "interaction.pending": (count: number) => `${count} pending`,
  "interaction.cancel": "Cancel",
  "interaction.submit": "Submit",

  // Copy
  "copy.copy": "Copy",
  "copy.copied": "Copied",
  "copy.copyButton": "[Copy]",
  "copy.copiedButton": "[Copied]",

  // File search
  "fileSearch.searching": "Searching files...",

  // Tool block
  "tool.planning": "Planning\u2026",
  "tool.todoTitle": "Update To-Do",
  "tool.askingQuestion": "Asking user question\u2026",

  // Collapse group
  "collapse.read": "Read",
  "collapse.edited": "Edited",
  "collapse.wrote": "Wrote",
  "collapse.patched": "Patched",
  "collapse.ran": "Ran",
  "collapse.list": "List",
  "collapse.bashSearch": "Search",
  "collapse.fetch": "Fetch",
  "collapse.search": "Search",
  "collapse.thoughts": "Thoughts",
  "collapse.completed": "Completed",
  "collapse.toolsUsed": (count: number) => `${count} tool${count === 1 ? "" : "s"} used`,

  // User message
  "userMessage.showMore": "Show more",
  "userMessage.showLess": "Show less",

  // Diff view
  "diff.showMore": "Show more",
  "diff.showLess": "Show less",

  // Task metadata
  "taskMeta.interruptedAfter": "Interrupted after",
  "taskMeta.workedFor": "Worked for",
  "taskMeta.steps": (n: number) => `in ${n} ${n === 1 ? "step" : "steps"}`,
  "taskMeta.model": "Model",
  "taskMeta.provider": "Provider",
  "taskMeta.inputTokens": "Input tokens",
  "taskMeta.cacheRead": "Cache read",
  "taskMeta.cacheHitRate": (pct: number) => `(${pct}% hit)`,
  "taskMeta.cacheWrite": "Cache write",
  "taskMeta.outputTokens": "Output tokens",
  "taskMeta.reasoning": "Reasoning",
  "taskMeta.context": "Context",
  "taskMeta.cost": "Cost",
  "taskMeta.duration": "Duration",
  "taskMeta.throughput": "Throughput",
  "taskMeta.stepsLabel": "Steps",
  "taskMeta.stepsValue": (n: number) => `${n} ${n === 1 ? "step" : "steps"}`,
  "taskMeta.via": (provider: string) => `via ${provider}`,

  // Message list
  "messageList.scrollToBottom": "Scroll to bottom",

  // Developer summary
  "developer.summarySkill": (name: string) => `skill:${name}`,
  "developer.summaryFolderList": (n: number) => `${n} folder ${n === 1 ? "list" : "lists"}`,
  "developer.summaryReread": (n: number) => `${n} re-read ${n === 1 ? "file" : "files"}`,

  // Plurals
  "plural.memory": (n: number) => `${n} ${n === 1 ? "memory" : "memories"}`,
  "plural.file": (n: number) => `${n} ${n === 1 ? "file" : "files"}`,
  "plural.list": (n: number) => `${n} ${n === 1 ? "list" : "lists"}`,
  "plural.image": (n: number) => `${n} ${n === 1 ? "image" : "images"}`,
} as const;

export type TranslationKey = keyof typeof en;
export type Translations = {
  [K in TranslationKey]: (typeof en)[K] extends (...args: infer A) => string
    ? (...args: A) => string
    : string;
};
export default en;
