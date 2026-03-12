import { useState, useMemo, useRef, useEffect } from "react";

import type { ToolBlockItem } from "../../types/message";
import { useSearch } from "./search-context";
import { TodoListView } from "./TodoListView";
import { QuestionSummaryView } from "./QuestionSummaryView";
import { ToolBlockHeader } from "./ToolBlockHeader";
import { ToolBlockResult } from "./ToolBlockResult";
import { isQuestionSummaryUIExtra, isTodoListUIExtra } from "./message-ui-extra";
import { hasDiffUIExtra, hasRichUIExtra } from "./tool-rich-result-ui";
import { useStreamThrottle } from "./useStreamThrottle";

const PLAN_TOOLS = new Set(["TodoWrite", "update_plan"]);
const DEFAULT_EXPANDED_TOOLS = new Set(["apply_patch", "Edit", "Write"]);

function extractHeaderDetail(toolName: string, args: string): string {
  try {
    const parsed = JSON.parse(args);
    switch (toolName) {
      case "Bash":
        return typeof parsed.command === "string" ? parsed.command : "";
      case "Read":
        return typeof parsed.file_path === "string" ? parsed.file_path : "";
      case "Edit":
        return typeof parsed.file_path === "string" ? parsed.file_path : "";
      case "Write":
        return typeof parsed.file_path === "string" ? parsed.file_path : "";
      case "apply_patch": {
        const patch = typeof parsed.patch === "string" ? parsed.patch : "";
        const updates: string[] = [];
        const adds: string[] = [];
        const deletes: string[] = [];
        for (const line of patch.split("\n")) {
          if (line.startsWith("*** Update File:")) updates.push(line.slice(16).trim());
          else if (line.startsWith("*** Add File:")) adds.push(line.slice(13).trim());
          else if (line.startsWith("*** Delete File:")) deletes.push(line.slice(16).trim());
        }
        const parts: string[] = [];
        if (updates.length) parts.push(`Edit x${updates.length}`);
        if (adds.length) parts.push(`Create x${adds.length}`);
        if (deletes.length) parts.push(`Delete x${deletes.length}`);
        return parts.join(", ");
      }
      case "WebFetch":
        return typeof parsed.url === "string" ? parsed.url : "";
      case "WebSearch":
        return typeof parsed.query === "string" ? parsed.query : "";
      case "Glob":
        return typeof parsed.pattern === "string" ? parsed.pattern : "";
      case "Grep":
        return typeof parsed.pattern === "string" ? parsed.pattern : "";
      default:
        return "";
    }
  } catch {
    return "";
  }
}

function shouldExpandResult(item: ToolBlockItem): boolean {
  if (item.resultStatus === "error") return false;
  if (item.uiExtra !== null && hasRichUIExtra(item.uiExtra)) return true;
  if (DEFAULT_EXPANDED_TOOLS.has(item.toolName)) return true;
  if (item.toolName === "Read") return false;
  return false;
}

interface ToolBlockProps {
  item: ToolBlockItem;
  compact?: boolean;
  workDir?: string;
}

function extractPlanExplanation(args: string): string {
  try {
    const parsed = JSON.parse(args);
    if (typeof parsed.explanation === "string") return parsed.explanation.trim();
  } catch {
    /* ignore */
  }
  return "";
}

function PlanBlock({ item, compact = false }: ToolBlockProps): JSX.Element {
  const explanation = useMemo(() => {
    if (item.toolName === "update_plan") return extractPlanExplanation(item.arguments);
    return "";
  }, [item.toolName, item.arguments]);

  const todoExtra = item.uiExtra && isTodoListUIExtra(item.uiExtra) ? item.uiExtra : null;

  return (
    <div className="rounded-lg border border-neutral-200/80 bg-neutral-50/50 px-3.5 py-2 text-sm">
      {explanation ? (
        <p className="mb-1 font-sans text-sm text-neutral-500">{explanation}</p>
      ) : null}
      {todoExtra ? (
        <TodoListView uiExtra={todoExtra} compact={compact} />
      ) : item.isStreaming ? (
        <div className="flex items-center gap-1.5 font-sans text-sm text-neutral-400">
          <span className="h-3 w-3 animate-spin rounded-full border border-neutral-300 border-t-neutral-500" />
          <span>Planning…</span>
        </div>
      ) : null}
    </div>
  );
}

function QuestionBlock({ item, compact = false }: ToolBlockProps): JSX.Element {
  const questionExtra =
    item.uiExtra && isQuestionSummaryUIExtra(item.uiExtra) ? item.uiExtra : null;

  return (
    <div className="rounded-lg border border-neutral-200/80 bg-neutral-50/50 px-3.5 py-2 text-sm">
      {questionExtra ? (
        <QuestionSummaryView uiExtra={questionExtra} compact={compact} />
      ) : item.isStreaming ? (
        <div className="flex items-center gap-1.5 font-sans text-sm text-neutral-400">
          <span className="h-3 w-3 animate-spin rounded-full border border-neutral-300 border-t-neutral-500" />
          <span>Waiting for answer…</span>
        </div>
      ) : null}
    </div>
  );
}

export function ToolBlock({ item, compact = false, workDir }: ToolBlockProps): JSX.Element {
  const { matchItemIds } = useSearch();
  const bodyTextClass = "text-sm";
  const headerDetailTextClass = "!text-sm";
  const detailChipClass = "rounded bg-neutral-100 px-1.5 py-0.5 align-middle";

  const defaultExpanded = shouldExpandResult(item);
  const [open, setOpen] = useState(defaultExpanded);
  const [showMore, setShowMore] = useState(false);
  const isSearchMatch = matchItemIds.includes(item.id);
  const wasAutoExpanded = useRef(false);

  // Auto-expand when search matches inside this tool block
  useEffect(() => {
    if (isSearchMatch && !open) {
      setOpen(true);
      wasAutoExpanded.current = true;
    }
    if (!isSearchMatch && wasAutoExpanded.current) {
      setOpen(defaultExpanded);
      wasAutoExpanded.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSearchMatch]);

  // Auto-expand when streaming content starts arriving
  const hasStreamingContent = item.streamingContent.length > 0;
  const streamingContent = useStreamThrottle(
    item.streamingContent,
    item.isStreaming && hasStreamingContent,
  );
  const streamAutoExpanded = useRef(false);
  useEffect(() => {
    if (hasStreamingContent && !open) {
      setOpen(true);
      streamAutoExpanded.current = true;
    }
  }, [hasStreamingContent, open]);

  if (PLAN_TOOLS.has(item.toolName)) {
    return <PlanBlock item={item} compact={compact} />;
  }
  if (item.toolName === "AskUserQuestion") {
    return <QuestionBlock item={item} compact={compact} />;
  }

  const detail = extractHeaderDetail(item.toolName, item.arguments);
  const hasResult = item.result !== null && item.result.length > 0;
  const isEmptyResult = item.result !== null && item.result.length === 0;
  const isError = item.resultStatus === "error";
  const hasRich = item.uiExtra !== null && hasRichUIExtra(item.uiExtra);
  const hideResultRail = item.uiExtra !== null && hasDiffUIExtra(item.uiExtra);
  const expandable = hasResult || isEmptyResult || hasRich || hasStreamingContent;

  const detailColor = isError
    ? "text-red-700"
    : item.resultStatus === "aborted"
      ? "text-neutral-400"
      : "text-neutral-400";

  return (
    <div
      className={`-my-1 grid grid-cols-[auto_1fr] items-center gap-x-1.5 ${bodyTextClass} font-mono ${expandable ? "cursor-pointer" : "cursor-default"}`}
      onClick={() => expandable && setOpen((v) => !v)}
    >
      <ToolBlockHeader
        item={item}
        expandable={expandable}
        open={open}
        detail={detail}
        detailColor={detailColor}
        workDir={workDir}
        headerDetailTextClass={headerDetailTextClass}
        detailChipClass={detailChipClass}
      />
      <ToolBlockResult
        item={item}
        compact={compact}
        open={open}
        hasRich={hasRich}
        hideResultRail={hideResultRail}
        hasResult={hasResult}
        hasStreamingContent={hasStreamingContent}
        streamingContent={streamingContent}
        isEmptyResult={isEmptyResult}
        isError={isError}
        showMore={showMore}
        onToggleShowMore={() => setShowMore((value) => !value)}
      />
    </div>
  );
}
