import { Loader } from "lucide-react";
import { useState, useRef, useEffect } from "react";

import { useT } from "@/i18n";
import type { ToolBlockItem } from "../../types/message";
import { COLLAPSE_RAIL_GRID_CLASS_NAME } from "./CollapseRail";
import { useCollapseAll } from "./collapse-all-context";
import { useSearch } from "./search-context";
import { TodoListView } from "./TodoListView";
import { QuestionSummaryView } from "./QuestionSummaryView";
import { ToolBlockHeader } from "./ToolBlockHeader";
import { ToolBlockResult } from "./ToolBlockResult";
import { isQuestionSummaryUIExtra, isTodoListUIExtra } from "./message-ui-extra";
import { hasRichUIExtra } from "./tool-rich-result-ui";
import { useStreamThrottle } from "./useStreamThrottle";

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
  workDir?: string;
}

function PlanBlock({ item }: ToolBlockProps): JSX.Element {
  const t = useT();
  const todoExtra = item.uiExtra && isTodoListUIExtra(item.uiExtra) ? item.uiExtra : null;

  return (
    <div className="w-fit rounded-lg border border-border/80 bg-surface/50 px-3.5 py-2.5 text-base">
      {todoExtra ? (
        <TodoListView uiExtra={todoExtra} />
      ) : item.isStreaming ? (
        <div className="flex items-center gap-1.5 font-sans text-base text-neutral-600">
          <Loader className="h-3 w-3 animate-spin text-neutral-500" />
          <span>{t("tool.planning")}</span>
        </div>
      ) : null}
    </div>
  );
}

function QuestionBlock({ item }: ToolBlockProps): JSX.Element {
  const t = useT();
  const questionExtra =
    item.uiExtra && isQuestionSummaryUIExtra(item.uiExtra) ? item.uiExtra : null;

  return (
    <div className="rounded-lg border border-border/80 bg-surface/50 px-3.5 py-2.5 text-base">
      {questionExtra ? (
        <QuestionSummaryView uiExtra={questionExtra} />
      ) : item.isStreaming ? (
        <div className="flex items-center gap-1.5 font-sans text-base text-neutral-600">
          <Loader className="h-3 w-3 animate-spin text-neutral-500" />
          <span>{t("tool.askingQuestion")}</span>
        </div>
      ) : null}
    </div>
  );
}

export function ToolBlock({ item, workDir }: ToolBlockProps): JSX.Element {
  const { matchItemIds } = useSearch();
  const { collapseGen, expandGen } = useCollapseAll();
  const bodyTextClass = "text-base";
  const headerDetailTextClass = "!text-sm";
  const detailChipClass = "rounded bg-surface px-1.5 py-0.5 align-middle leading-5";

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

  // Collapse all / expand all signals
  useEffect(() => {
    if (collapseGen > 0) setOpen(false);
  }, [collapseGen]);

  useEffect(() => {
    if (expandGen > 0) setOpen(true);
  }, [expandGen]);

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

  if (item.toolName === "TodoWrite") {
    return <PlanBlock item={item} />;
  }
  if (item.toolName === "AskUserQuestion") {
    return <QuestionBlock item={item} />;
  }

  const detail = extractHeaderDetail(item.toolName, item.arguments);
  const hasResult = item.result !== null && item.result.length > 0;
  const isEmptyResult = item.result !== null && item.result.length === 0;
  const isError = item.resultStatus === "error";
  const hasRich = item.uiExtra !== null && hasRichUIExtra(item.uiExtra);
  const expandable = hasResult || isEmptyResult || hasRich || hasStreamingContent;

  const detailColor = isError
    ? "text-red-700"
    : item.resultStatus === "aborted"
      ? "text-neutral-600"
      : "text-neutral-600";

  return (
    <div
      className={`-my-1 grid items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME} ${bodyTextClass} font-mono ${expandable ? "cursor-pointer" : "cursor-default"}`}
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
        open={open}
        hasRich={hasRich}
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
