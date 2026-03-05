import { useState } from "react";
import {
  ChevronRight,
  Loader2,
  Terminal,
  FileText,
  FilePenLine,
  FilePlus,
  FileDiff,
  ListChecks,
  Globe,
  Search,
  CircleHelp,
  CheckCircle,
  Undo2,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/collapsible";
import type { ToolBlockItem } from "../../types/message";
import { DiffView } from "./DiffView";

const TOOL_ICONS: Record<string, LucideIcon> = {
  Bash: Terminal,
  Read: FileText,
  Edit: FilePenLine,
  Write: FilePlus,
  apply_patch: FileDiff,
  TodoWrite: ListChecks,
  update_plan: ListChecks,
  WebFetch: Globe,
  WebSearch: Search,
  AskUserQuestion: CircleHelp,
  report_back: CheckCircle,
  Rewind: Undo2,
};

const SKIP_ICON_TOOLS = new Set(["Agent"]);

// Tools whose result is expanded by default
const EXPAND_RESULT_TOOLS = new Set([
  "diff",
  "read_preview",
  "todo_list",
  "ask_user_question_summary",
  "image",
]);

function getToolIcon(toolName: string): LucideIcon | null {
  if (SKIP_ICON_TOOLS.has(toolName)) return null;
  return TOOL_ICONS[toolName] ?? Wrench;
}

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
  if (item.toolName === "Read") return false;
  if (item.uiExtra !== null) return true;
  if (EXPAND_RESULT_TOOLS.has(item.toolName)) return true;
  return false;
}

interface ToolBlockProps {
  item: ToolBlockItem;
}

export function ToolBlock({ item }: ToolBlockProps): JSX.Element {
  const defaultExpanded = shouldExpandResult(item);
  const [open, setOpen] = useState(defaultExpanded);

  const Icon = getToolIcon(item.toolName);
  const detail = extractHeaderDetail(item.toolName, item.arguments);
  const isBash = item.toolName === "Bash";
  const hasResult = item.result !== null && item.result.length > 0;
  const isError = item.resultStatus === "error";
  const hasDiff = item.uiExtra !== null && (item.uiExtra as Record<string, unknown>).type === "diff";

  const leftColor = isError || item.resultStatus === "aborted"
    ? "border-l-red-400"
    : item.resultStatus === "success"
      ? "border-l-emerald-500"
      : "border-l-zinc-300";

  return (
    <div className={`rounded-md border border-zinc-200/80 border-l-[3px] ${leftColor}`}>
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex items-center gap-2 px-3 py-2 text-sm w-full cursor-pointer group">
          {Icon ? <Icon className="w-3.5 h-3.5 text-zinc-400 shrink-0" /> : null}
          <span className="font-medium text-zinc-600">{item.toolName}</span>
          {detail ? (
            isBash ? (
              <code className="bg-zinc-50 rounded px-1.5 py-0.5 text-xs font-mono text-zinc-500 truncate min-w-0">
                {detail}
              </code>
            ) : (
              <span className="text-zinc-400 truncate min-w-0">{detail}</span>
            )
          ) : null}
          <span className="flex-1" />
          {item.isStreaming ? (
            <Loader2 className="w-3.5 h-3.5 text-zinc-400 animate-spin shrink-0" />
          ) : null}
          {hasResult || hasDiff ? (
            <ChevronRight
              className={`w-3.5 h-3.5 text-zinc-300 transition-transform duration-150 shrink-0 ${open ? "rotate-90" : ""}`}
            />
          ) : null}
        </CollapsibleTrigger>
        {hasDiff ? (
          <CollapsibleContent>
            <div className="px-3 pt-1 pb-2">
              <div className="rounded-lg border border-zinc-200/80 overflow-hidden">
                <DiffView item={item} />
              </div>
            </div>
          </CollapsibleContent>
        ) : hasResult ? (
          <CollapsibleContent>
            <pre
              className={`px-3 pt-1 pb-2 text-xs leading-relaxed whitespace-pre-wrap break-words font-mono ${
                isError ? "text-red-600" : "text-zinc-500"
              }`}
            >
              {item.result}
            </pre>
          </CollapsibleContent>
        ) : null}
      </Collapsible>
    </div>
  );
}
