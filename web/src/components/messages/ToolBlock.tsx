import { useState, useRef, useEffect } from "react";

import { useT } from "@/i18n";
import type { ToolBlockItem } from "@/types/message";
import { COLLAPSE_RAIL_GRID_CLASS_NAME, CollapseRailMarker } from "./CollapseRail";
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

interface ToolHeaderMeta {
  detail: string;
  description: string;
}

function extractHeaderMeta(toolName: string, args: string): ToolHeaderMeta {
  try {
    const parsed = JSON.parse(args) as Record<string, unknown>;
    switch (toolName) {
      case "Bash":
        return {
          detail: typeof parsed.command === "string" ? parsed.command : "",
          description: typeof parsed.description === "string" ? parsed.description : "",
        };
      case "Read":
        return {
          detail: typeof parsed.file_path === "string" ? parsed.file_path : "",
          description: "",
        };
      case "Edit":
        return {
          detail: typeof parsed.file_path === "string" ? parsed.file_path : "",
          description: "",
        };
      case "Write":
        return {
          detail: typeof parsed.file_path === "string" ? parsed.file_path : "",
          description: "",
        };
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
        return { detail: parts.join(", "), description: "" };
      }
      case "WebFetch":
        return {
          detail: typeof parsed.url === "string" ? parsed.url : "",
          description: "",
        };
      case "WebSearch":
        return {
          detail: typeof parsed.query === "string" ? parsed.query : "",
          description: "",
        };
      default:
        return { detail: "", description: "" };
    }
  } catch {
    return { detail: "", description: "" };
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

function PlanBlock({ item }: ToolBlockProps): React.JSX.Element {
  const t = useT();
  const todoExtra = item.uiExtra && isTodoListUIExtra(item.uiExtra) ? item.uiExtra : null;

  return (
    <div className="w-fit rounded-lg bg-surface/50 px-3 py-1.5 text-base shadow-sm ring-1 ring-inset ring-black/10">
      {todoExtra ? (
        <TodoListView uiExtra={todoExtra} />
      ) : item.isStreaming ? (
        <div className="font-sans text-xs">
          <span className="text-shimmer">{t("tool.planning")}</span>
        </div>
      ) : null}
    </div>
  );
}

function QuestionBlock({ item }: ToolBlockProps): React.JSX.Element {
  const t = useT();
  const questionExtra =
    item.uiExtra && isQuestionSummaryUIExtra(item.uiExtra) ? item.uiExtra : null;

  return (
    <div className="rounded-lg bg-surface/50 px-3.5 py-2.5 text-base shadow-sm ring-1 ring-inset ring-black/10">
      {questionExtra ? (
        <QuestionSummaryView uiExtra={questionExtra} />
      ) : item.isStreaming ? (
        <div className="font-sans text-xs">
          <span className="text-shimmer">{t("tool.askingQuestion")}</span>
        </div>
      ) : null}
    </div>
  );
}

export function ToolBlock({ item, workDir }: ToolBlockProps): React.JSX.Element {
  const { matchItemIds } = useSearch();
  const { collapseGen, expandGen } = useCollapseAll();
  const bodyTextClass = "text-base";
  const headerDetailTextClass = "!text-sm";
  const detailChipClass = "align-middle leading-5";

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

  const { detail, description } = extractHeaderMeta(item.toolName, item.arguments);
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
      className={`grid items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME} ${bodyTextClass} ${expandable ? "cursor-pointer" : "cursor-default"}`}
      onClick={() => {
        if (expandable) setOpen((v) => !v);
      }}
    >
      <CollapseRailMarker
        open={open}
        expandable={expandable}
        className="row-span-2 text-sm leading-5"
      />
      <ToolBlockHeader
        item={item}
        detail={detail}
        description={description}
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
        onToggleShowMore={() => {
          setShowMore((value) => !value);
        }}
      />
    </div>
  );
}
