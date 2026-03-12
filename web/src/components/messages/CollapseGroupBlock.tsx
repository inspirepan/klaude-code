import { useMemo } from "react";

import type { MessageItem as MessageItemType } from "../../types/message";
import { MessageRow } from "./MessageRow";

interface CollapseGroupBlockProps {
  items: MessageItemType[];
  collapsed: boolean;
  onToggle: () => void;
  activeItemId: string | null;
  copiedItemId: string | null;
  workDir: string;
  onCopy: (item: MessageItemType) => void | Promise<void>;
  setItemRef: (id: string, el: HTMLDivElement | null) => void;
}

// Commands that take a meaningful subcommand as their second token
const SUBCOMMAND_COMMANDS = new Set([
  "git", "jj", "hg", "svn",
  "docker", "docker-compose", "podman", "kubectl", "helm",
  "npm", "yarn", "pnpm", "cargo", "uv", "pip", "poetry",
  "brew", "apt", "apt-get", "dnf", "yum", "pacman",
  "aws", "gcloud", "az",
  "go", "rustup", "python", "ruby",
  "gh", "systemctl", "launchctl", "supervisorctl",
]);

interface SummaryPart {
  label: string;
  value: string;
}

function basename(path: string): string {
  return path.split("/").pop() ?? path;
}

function extractBashSummary(command: string): string {
  // Take only the first statement (before &&, ||, ;, |, newline)
  const first = command.split(/&&|\|\||[;|\n]/)[0]?.trim() ?? command;
  const tokens = first.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return command.slice(0, 30);
  const cmd = tokens[0]!;
  if (SUBCOMMAND_COMMANDS.has(cmd)) {
    for (let i = 1; i < tokens.length; i++) {
      if (!tokens[i]!.startsWith("-")) {
        return `${cmd} ${tokens[i]}`;
      }
    }
  }
  return cmd;
}

function summarizeCollapseItems(items: MessageItemType[]): SummaryPart[] {
  const grouped = new Map<string, string[]>();

  for (const item of items) {
    if (item.type !== "tool_block") continue;
    let args: Record<string, unknown>;
    try {
      args = JSON.parse(item.arguments) as Record<string, unknown>;
    } catch {
      continue;
    }

    const name = item.toolName;
    if (!grouped.has(name)) grouped.set(name, []);
    const bucket = grouped.get(name)!;

    switch (name) {
      case "Read": {
        const p = typeof args.file_path === "string" ? basename(args.file_path) : null;
        if (p) bucket.push(p);
        break;
      }
      case "Bash": {
        const s = typeof args.command === "string" ? extractBashSummary(args.command) : null;
        if (s) bucket.push(s);
        break;
      }
      case "Glob": {
        const p = typeof args.pattern === "string" ? args.pattern : null;
        if (p) bucket.push(p);
        break;
      }
      case "Grep": {
        const p = typeof args.pattern === "string" ? args.pattern : null;
        if (p) bucket.push(p);
        break;
      }
      case "WebFetch": {
        try {
          const host = typeof args.url === "string" ? new URL(args.url).hostname : null;
          if (host) bucket.push(host);
        } catch { /* ignore invalid URLs */ }
        break;
      }
      case "WebSearch": {
        const q = typeof args.query === "string" ? args.query : null;
        if (q) bucket.push(q);
        break;
      }
    }
  }

  const parts: SummaryPart[] = [];
  for (const [name, values] of grouped) {
    if (values.length === 0) continue;
    const unique = [...new Set(values)];
    switch (name) {
      case "Read": {
        const shown = unique.slice(0, 3).join(", ");
        const value = unique.length > 3 ? `${shown} +${unique.length - 3}` : shown;
        parts.push({ label: "Read", value });
        break;
      }
      case "Bash":
        parts.push({ label: "Ran", value: unique.slice(0, 2).join(", ") });
        break;
      case "Glob":
        parts.push({ label: "Glob", value: unique[0]! });
        break;
      case "Grep":
        parts.push({ label: "Grep", value: unique[0]! });
        break;
      case "WebFetch":
        parts.push({ label: "Fetch", value: unique[0]! });
        break;
      case "WebSearch": {
        const q = unique[0]!;
        parts.push({ label: "Search", value: q.length > 30 ? q.slice(0, 30) + "…" : q });
        break;
      }
    }
  }

  return parts;
}

export function CollapseGroupBlock({
  items,
  collapsed,
  onToggle,
  activeItemId,
  copiedItemId,
  workDir,
  onCopy,
  setItemRef,
}: CollapseGroupBlockProps): JSX.Element {
  const toolCount = items.filter((item) => item.type === "tool_block").length;
  const stepLabel = toolCount > 0 ? `${toolCount} tool${toolCount === 1 ? "" : "s"} used` : "Thoughts";
  const summary = useMemo(() => summarizeCollapseItems(items), [items]);

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex min-w-0 items-center gap-1.5 py-0.5 text-left text-sm text-neutral-400 transition-colors hover:text-neutral-600"
      >
        <span className="shrink-0 font-mono text-xs text-neutral-300">{collapsed ? "[+]" : "[-]"}</span>
        <span className="shrink-0">{stepLabel}</span>
        {summary.length > 0 ? (
          <span className="flex min-w-0 items-center truncate pl-2">
            {summary.map((part, i) => (
              <span key={i} className={`flex shrink-0 items-center gap-1 ${i < summary.length - 1 ? "mr-2" : ""}`}>
                <span className="text-neutral-500">{part.label}</span>
                <span className="font-mono text-neutral-400">{part.value}</span>
                {i < summary.length - 1 ? <span className="text-neutral-300">,</span> : null}
              </span>
            ))}
          </span>
        ) : null}
      </button>
      {/* grid-template-rows trick: 0fr→1fr gives smooth height transition without JS height measurement */}
      <div
        className="grid transition-[grid-template-rows,opacity] duration-200 ease-in-out"
        style={{
          gridTemplateRows: collapsed ? "0fr" : "1fr",
          opacity: collapsed ? 0 : 1,
        }}
      >
        <div className="overflow-hidden">
          <div className="mt-3 grid grid-cols-[28px_1fr]">
            <div className="flex justify-center pt-1">
              <div className="w-px bg-neutral-200" />
            </div>
            <div className="min-w-0 space-y-5 pb-1">
              {items.map((item) => (
                <MessageRow
                  key={item.id}
                  item={item}
                  variant="main"
                  workDir={workDir}
                  isActive={item.id === activeItemId}
                  copied={copiedItemId === item.id}
                  onCopy={onCopy}
                  itemRef={(el: HTMLDivElement | null) => setItemRef(item.id, el)}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
