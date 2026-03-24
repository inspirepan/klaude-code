import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { useT } from "@/i18n";
import type { MessageItem as MessageItemType, DeveloperMessageItem } from "../../types/message";
import type { CollapseGroupEntry, SectionSubAgentBlock } from "./message-sections";
import { formatSubAgentTypeLabel } from "./message-list-ui";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import {
  COLLAPSE_RAIL_GRID_CLASS_NAME,
  CollapseRailConnector,
  CollapseRailMarker,
  CollapseRailPanel,
} from "./CollapseRail";
import { isDiffUIExtra, type DiffUIExtra } from "./message-ui-extra";
import { MessageRow } from "./MessageRow";
import { DeveloperMessage } from "./DeveloperMessage";
import { parseBashCommand } from "./parse-bash-command";

interface CollapseGroupBlockProps {
  entries: CollapseGroupEntry[];
  collapsed: boolean;
  onToggle: () => void;
  activeItemId: string | null;
  copiedItemId: string | null;
  workDir: string;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
  renderSubAgent?: (entry: SectionSubAgentBlock) => ReactNode;
}

interface FileStat {
  name: string;
  del?: number;
  add: number;
}

interface SummaryPart {
  label: string;
  value: string;
  del?: number;
  add?: number;
  fileStats?: FileStat[];
  mono?: boolean;
}

function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

function extractApplyPatchFileStats(patch: string): FileStat[] {
  const fileStats: FileStat[] = [];
  let current: FileStat | null = null;

  const pushCurrent = () => {
    if (current !== null) fileStats.push(current);
  };

  for (const line of patch.split("\n")) {
    if (line.startsWith("*** Update File: ")) {
      pushCurrent();
      current = { name: basename(line.slice(17).trim()), del: 0, add: 0 };
      continue;
    }
    if (line.startsWith("*** Add File: ")) {
      pushCurrent();
      current = { name: basename(line.slice(13).trim()), del: 0, add: 0 };
      continue;
    }
    if (line.startsWith("*** Delete File: ")) {
      pushCurrent();
      current = { name: basename(line.slice(16).trim()), del: 0, add: 0 };
      continue;
    }
    if (line.startsWith("*** ")) continue;
    if (current === null) continue;
    if (line.startsWith("+")) current.add += 1;
    else if (line.startsWith("-")) current.del = (current.del ?? 0) + 1;
  }

  pushCurrent();
  if (fileStats.length > 0) return fileStats;

  let unifiedCurrent: FileStat | null = null;
  for (const line of patch.split("\n")) {
    const fileMatch = line.match(/^\+\+\+ b\/(.+)$/) ?? line.match(/^--- a\/(.+)$/);
    if (fileMatch) {
      const name = basename(fileMatch[1]);
      if (unifiedCurrent === null || unifiedCurrent.name !== name) {
        if (unifiedCurrent !== null) fileStats.push(unifiedCurrent);
        unifiedCurrent = { name, del: 0, add: 0 };
      }
      continue;
    }
    if (line.startsWith("+++ ") || line.startsWith("--- ")) continue;
    if (unifiedCurrent === null) continue;
    if (line.startsWith("+")) unifiedCurrent.add += 1;
    else if (line.startsWith("-")) unifiedCurrent.del = (unifiedCurrent.del ?? 0) + 1;
  }

  if (unifiedCurrent !== null) fileStats.push(unifiedCurrent);
  return fileStats;
}

function extractDiffStats(
  uiExtra: Record<string, unknown> | null,
): { del: number; add: number } | null {
  if (!uiExtra) return null;
  const extras: DiffUIExtra[] = isDiffUIExtra(uiExtra)
    ? [uiExtra]
    : uiExtra.type === "multi" && Array.isArray(uiExtra.items)
      ? (uiExtra.items as unknown[]).filter(isDiffUIExtra)
      : [];
  if (extras.length === 0) return null;
  let del = 0;
  let add = 0;
  for (const extra of extras) {
    for (const file of extra.files) {
      del += file.stats_remove;
      add += file.stats_add;
    }
  }
  return { del, add };
}

function mergeFileStats(
  files: Array<{ name: string; del: number; add: number }>,
): Array<{ name: string; del: number; add: number }> {
  const merged = new Map<string, { del: number; add: number }>();
  for (const f of files) {
    const existing = merged.get(f.name);
    if (existing) {
      existing.del += f.del;
      existing.add += f.add;
    } else {
      merged.set(f.name, { del: f.del, add: f.add });
    }
  }
  return [...merged.entries()].map(([name, s]) => ({ name, del: s.del, add: s.add }));
}

function summarizeCollapseEntries(
  entries: CollapseGroupEntry[],
  t: ReturnType<typeof useT>,
): SummaryPart[] {
  // --- Collection phase ---
  const readFiles: string[] = [];
  const editFiles: Array<{ name: string; del: number; add: number }> = [];
  const writeFiles: Array<{ name: string; del: number; add: number }> = [];
  const patchFiles: Array<{ name: string; del: number; add: number }> = [];
  const bashLists: Array<string | null> = [];
  const bashSearches: Array<{ query: string | null; path: string | null }> = [];
  const bashRuns: string[] = [];
  const webFetches: string[] = [];
  const webSearches: string[] = [];
  const agents: Array<{ type: string; desc: string | null }> = [];

  for (const entry of entries) {
    if (entry.type === "sub_agent_group") {
      agents.push({
        type: formatSubAgentTypeLabel(entry.sourceSessionType),
        desc: entry.sourceSessionDesc,
      });
      continue;
    }
    const item = entry;
    if (item.type !== "tool_block") continue;
    let args: Record<string, unknown>;
    try {
      args = JSON.parse(item.arguments) as Record<string, unknown>;
    } catch {
      continue;
    }

    switch (item.toolName) {
      case "Read": {
        const p = typeof args.file_path === "string" ? basename(args.file_path) : null;
        if (p) readFiles.push(p);
        break;
      }
      case "Edit": {
        const p = typeof args.file_path === "string" ? basename(args.file_path) : null;
        if (!p) break;
        const diffStats = extractDiffStats(item.uiExtra);
        editFiles.push({
          name: p,
          del:
            diffStats?.del ??
            (typeof args.old_string === "string" ? args.old_string.split("\n").length : 0),
          add:
            diffStats?.add ??
            (typeof args.new_string === "string" ? args.new_string.split("\n").length : 0),
        });
        break;
      }
      case "Write": {
        const p = typeof args.file_path === "string" ? basename(args.file_path) : null;
        if (!p) break;
        const diffStats = extractDiffStats(item.uiExtra);
        writeFiles.push({
          name: p,
          del: diffStats?.del ?? 0,
          add:
            diffStats?.add ??
            (typeof args.content === "string" ? args.content.split("\n").length : 0),
        });
        break;
      }
      case "apply_patch": {
        const patch = typeof args.patch === "string" ? args.patch : null;
        if (!patch) break;
        const fileStats = extractApplyPatchFileStats(patch);
        if (fileStats.length === 0) {
          const lines = patch.split("\n");
          patchFiles.push({
            name: "patch",
            del: lines.filter((l) => l.startsWith("-") && !l.startsWith("---")).length,
            add: lines.filter((l) => l.startsWith("+") && !l.startsWith("+++")).length,
          });
        } else {
          for (const fs of fileStats)
            patchFiles.push({ name: fs.name, del: fs.del ?? 0, add: fs.add });
        }
        break;
      }
      case "Bash": {
        const parsed = typeof args.command === "string" ? parseBashCommand(args.command) : [];
        for (const cmd of parsed) {
          switch (cmd.type) {
            case "read":
              readFiles.push(cmd.name);
              break;
            case "list":
              bashLists.push(cmd.path);
              break;
            case "search":
              bashSearches.push({ query: cmd.query, path: cmd.path });
              break;
            case "run":
              bashRuns.push(cmd.cmd);
              break;
          }
        }
        break;
      }
      case "WebFetch": {
        try {
          const host = typeof args.url === "string" ? new URL(args.url).hostname : null;
          if (host) webFetches.push(host);
        } catch {
          /* ignore invalid URLs */
        }
        break;
      }
      case "WebSearch": {
        const q = typeof args.query === "string" ? args.query : null;
        if (q) webSearches.push(q);
        break;
      }
    }
  }

  // --- Build summary parts in display order ---
  const parts: SummaryPart[] = [];

  // 1. Edits
  if (editFiles.length > 0) {
    parts.push({ label: t("collapse.edited"), value: "", fileStats: mergeFileStats(editFiles) });
  }

  // 2. Writes
  if (writeFiles.length > 0) {
    const merged = mergeFileStats(writeFiles);
    parts.push({
      label: t("collapse.wrote"),
      value: "",
      fileStats: merged.map((f) => ({ name: f.name, add: f.add })),
    });
  }

  // 3. Patches
  if (patchFiles.length > 0) {
    parts.push({ label: t("collapse.patched"), value: "", fileStats: mergeFileStats(patchFiles) });
  }

  // 4. Sub-agents (significant delegated work -- show before reads)
  if (agents.length > 0) {
    if (agents.length === 1) {
      const a = agents[0];
      parts.push({ label: a.desc ? `${a.type}:` : a.type, value: a.desc ?? "", mono: false });
    } else {
      const byType = new Map<string, number>();
      for (const a of agents) byType.set(a.type, (byType.get(a.type) ?? 0) + 1);
      const value = [...byType.entries()]
        .map(([type, count]) => (count > 1 ? `${type} x${count}` : type))
        .join(", ");
      parts.push({ label: value, value: "", mono: false });
    }
  }

  // 5. Reads (tool Read + bash read commands like cat/head/tail)
  if (readFiles.length > 0) {
    const unique = [...new Set(readFiles)];
    const shown = unique.slice(0, 3).join(", ");
    const value = unique.length > 3 ? `${shown} +${unique.length - 3}` : shown;
    parts.push({ label: t("collapse.read"), value });
  }

  // 6. Bash list (ls/tree/rg --files/fd/find)
  if (bashLists.length > 0) {
    const uniquePaths = [...new Set(bashLists.filter(Boolean) as string[])];
    const value =
      uniquePaths.length > 3
        ? `${uniquePaths.slice(0, 3).join(", ")} +${uniquePaths.length - 3}`
        : uniquePaths.join(", ");
    parts.push({ label: t("collapse.list"), value });
  }

  // 7. Bash search (rg/grep/ag/ack/fd/find with query)
  if (bashSearches.length > 0) {
    const first = bashSearches[0];
    let value = "";
    if (first.query) {
      value = first.query;
      if (first.path) value += ` in ${first.path}`;
    } else if (first.path) {
      value = `in ${first.path}`;
    }
    if (bashSearches.length > 1) value += ` +${bashSearches.length - 1}`;
    parts.push({ label: t("collapse.bashSearch"), value });
  }

  // 8. Bash run (unknown commands: git commit, npm build, etc.)
  if (bashRuns.length > 0) {
    const unique = [...new Set(bashRuns)];
    parts.push({
      label: t("collapse.ran"),
      value:
        unique.length > 5
          ? `${unique.slice(0, 5).join(", ")} +${unique.length - 5}`
          : unique.join(", "),
    });
  }

  // 9. WebFetch
  if (webFetches.length > 0) {
    parts.push({ label: t("collapse.fetch"), value: [...new Set(webFetches)][0] });
  }

  // 10. WebSearch
  if (webSearches.length > 0) {
    const q = webSearches[0];
    parts.push({
      label: t("collapse.search"),
      value: q,
    });
  }

  return parts;
}

function summaryToText(summary: SummaryPart[]): string {
  return summary
    .map((part) => {
      if (part.fileStats) {
        const files = part.fileStats
          .map((fs) => {
            const stats = fs.del !== undefined ? `(-${fs.del} +${fs.add})` : `(+${fs.add})`;
            return `${fs.name} ${stats}`;
          })
          .join(", ");
        return `${part.label} ${files}`;
      }
      return `${part.label} ${part.value}`;
    })
    .join(" \u00b7 ");
}

function SummaryDisplay({ summary }: { summary: SummaryPart[] }): React.JSX.Element {
  return (
    <>
      {summary.map((part, partIdx) => (
        <span key={partIdx}>
          {partIdx > 0 ? <span className="mx-1.5 text-neutral-400">{"\u00b7"}</span> : null}
          {part.fileStats ? (
            <>
              <span className="font-normal text-neutral-500">{part.label}</span>{" "}
              {part.fileStats.map((fs, fsIdx) => (
                <span key={fsIdx}>
                  {fsIdx > 0 ? ", " : null}
                  <span className="font-mono text-[0.9em]">{fs.name}</span>
                  {" ( "}
                  {fs.del !== undefined && fs.del > 0 ? (
                    <span className="text-red-600">-{fs.del}</span>
                  ) : null}
                  {fs.del !== undefined && fs.del > 0 && fs.add > 0 ? " " : null}
                  {fs.add > 0 ? <span className="text-emerald-600">+{fs.add}</span> : null}
                  {" )"}
                </span>
              ))}
            </>
          ) : (
            <>
              <span className="font-normal text-neutral-500">{part.label}</span>{" "}
              <span className={part.mono === false ? "" : "font-mono text-[0.9em]"}>
                {part.value}
              </span>
            </>
          )}
        </span>
      ))}
    </>
  );
}

export function CollapseGroupBlock({
  entries,
  collapsed,
  onToggle,
  activeItemId,
  copiedItemId,
  workDir,
  onCopy,
  setItemRef,
  renderSubAgent,
}: CollapseGroupBlockProps): React.JSX.Element {
  const t = useT();
  const items = useMemo(
    () => entries.filter((e): e is MessageItemType => e.type !== "sub_agent_group"),
    [entries],
  );
  const summary = useMemo(() => summarizeCollapseEntries(entries, t), [entries, t]);
  // When detailed summary is empty (e.g. args not yet arrived during streaming),
  // show tool names as a stable fallback instead of the generic "Used N tools"
  // count, which causes a flash when the real summary appears.
  const fallbackLabel = useMemo(() => {
    const toolNames = items
      .filter((item) => item.type === "tool_block")
      .map((item) => item.toolName);
    const agentLabels = entries
      .filter((e): e is SectionSubAgentBlock => e.type === "sub_agent_group")
      .map((e) => formatSubAgentTypeLabel(e.sourceSessionType));
    const allNames = [...toolNames, ...agentLabels];
    if (allNames.length === 0) return t("collapse.thoughts");
    const counts = new Map<string, number>();
    for (const name of allNames) counts.set(name, (counts.get(name) ?? 0) + 1);
    return [...counts.entries()]
      .map(([name, count]) => (count > 1 ? `${name} x${count}` : name))
      .join(", ");
  }, [items, entries, t]);
  const summaryText = useMemo(() => summaryToText(summary), [summary]);
  const summarySpanRef = useRef<HTMLSpanElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  useEffect(() => {
    const el = summarySpanRef.current;
    if (!el) return;
    const check = () => {
      setIsTruncated(el.scrollWidth > el.clientWidth);
    };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [summaryText]);

  // Group consecutive entries for rendering: dev messages merge, sub-agents render via callback
  type RenderBlock =
    | { kind: "dev"; items: DeveloperMessageItem[] }
    | { kind: "other"; item: MessageItemType }
    | { kind: "sub_agent"; entry: SectionSubAgentBlock };

  const renderBlocks = useMemo((): RenderBlock[] => {
    const result: RenderBlock[] = [];
    for (const entry of entries) {
      if (entry.type === "sub_agent_group") {
        result.push({ kind: "sub_agent", entry });
        continue;
      }
      if (entry.type === "developer_message") {
        const last = result.at(-1);
        if (last?.kind === "dev") {
          last.items.push(entry);
        } else {
          result.push({ kind: "dev", items: [entry] });
        }
      } else {
        result.push({ kind: "other", item: entry });
      }
    }
    return result;
  }, [entries]);

  return (
    <div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onToggle}
            className={`grid w-full min-w-0 ${COLLAPSE_RAIL_GRID_CLASS_NAME} items-start py-1 text-left text-sm text-neutral-500 transition-colors hover:text-neutral-600`}
          >
            <CollapseRailMarker open={!collapsed} />
            <span className="flex min-w-0 items-center">
              {summary.length === 0 ? (
                <span className="min-w-0 truncate">{fallbackLabel}</span>
              ) : (
                <span ref={summarySpanRef} className="min-w-0 truncate text-neutral-500">
                  <SummaryDisplay summary={summary} />
                </span>
              )}
            </span>
          </button>
        </TooltipTrigger>
        {isTruncated ? (
          <TooltipContent side="bottom" align="end">
            {summaryText}
          </TooltipContent>
        ) : null}
      </Tooltip>
      {/* grid-template-rows trick: 0fr->1fr gives smooth height transition without JS height measurement */}
      <CollapseRailPanel open={!collapsed}>
        <div className={`mt-1.5 grid min-w-0 items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME}`}>
          <CollapseRailConnector lineClassName="-mt-1.5" />
          <div className="min-w-0 space-y-3 pb-1">
            {renderBlocks.map((block, idx) => {
              if (block.kind === "dev") {
                return <DeveloperMessage key={`dev-${idx}`} items={block.items} />;
              }
              if (block.kind === "sub_agent") {
                return renderSubAgent ? renderSubAgent(block.entry) : null;
              }
              return (
                <MessageRow
                  key={block.item.id}
                  item={block.item}
                  workDir={workDir}
                  isActive={block.item.id === activeItemId}
                  copied={copiedItemId === block.item.id}
                  onCopy={onCopy}
                  itemRef={(el: HTMLDivElement | null) => {
                    setItemRef(block.item.id, el);
                  }}
                />
              );
            })}
          </div>
        </div>
      </CollapseRailPanel>
    </div>
  );
}
